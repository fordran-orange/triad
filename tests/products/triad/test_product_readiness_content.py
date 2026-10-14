"""Offline document checks; these do not verify browser navigation or rendering."""

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import unquote
import pytest

pytestmark = pytest.mark.triad


PRODUCT_HTML = (
    Path(__file__).resolve().parents[3]
    / 'app/products/triad/static/product.html'
)


class Element:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def elements(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.elements()

    def text(self):
        return ''.join(
            child.text() if isinstance(child, Element) else child
            for child in self.children
        )


class ProductParser(HTMLParser):
    VOID_TAGS = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element('document')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in self.VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


class ProductReadinessContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parser = ProductParser()
        parser.feed(PRODUCT_HTML.read_text(encoding='utf-8'))
        parser.close()
        cls.document = parser.root
        cls.elements = list(cls.document.elements())
        cls.links = [node for node in cls.elements if node.tag == 'a']

    def test_ledger_workspace_structure(self):
        ids = [n.attrs["id"] for n in self.elements if "id" in n.attrs]
        self.assertEqual(len(ids), len(set(ids)))
        nodes = {n.attrs.get("id"): n for n in self.elements}
        section = nodes["trade-ledger"]
        self.assertEqual(section.tag, "section")
        labels = {n.attrs.get("for") for n in section.elements() if n.tag == "label"}
        self.assertTrue({"ledger-balance", "ledger-csv"} <= labels)
        self.assertEqual(nodes["ledger-csv"].tag, "textarea")
        self.assertEqual(nodes["ledger-status"].attrs.get("role"), "status")
        self.assertEqual(nodes["ledger-table"].tag, "table")
        self.assertIn("disabled", nodes["ledger-download"].attrs)
        self.assertIn("hidden", nodes["ledger-results"].attrs)
        for phrase in ("realized P&L only", "mark-to-market", "intratrade drawdown",
                       "Cash flows", "open positions", "capital/margin feasibility",
                       "Costs are deducted once", "illustrative sample"):
            self.assertIn(phrase, section.text())
        source = PRODUCT_HTML.read_text(encoding="utf-8")
        self.assertIn("/triad/product-api/research/trade-ledger", source)
        self.assertIn("if (current !== version) return;", source)

    def test_exposure_document_and_source_contract(self):
        nodes = {n.attrs.get("id"): n for n in self.elements}
        results = nodes["ledger-results"]
        self.assertIn("hidden", results.attrs)
        result_ids = [n.attrs.get("id") for n in results.elements()]
        for identifier in ("ledger-exposure-summary", "ledger-exposure-table", "ledger-exposure-rows"):
            self.assertEqual(result_ids.count(identifier), 1)
        table = nodes["ledger-exposure-table"]
        self.assertEqual([n.text() for n in table.elements() if n.tag == "caption"],
                         ["Chronological entry notional exposure — grouped UTC events; amounts in USD"])
        self.assertEqual([n.text() for n in table.elements() if n.tag == "th"], [
            "Timestamp (UTC)", "Active trades", "Long entry notional (USD)",
            "Short entry notional (USD)", "Gross entry notional (USD)",
            "Net entry notional (USD)", "Gross entry notional divided by initial balance (ratio)"])
        text = nodes["trade-ledger"].text()
        for phrase in ("additive extension", "triad.trade-ledger.v1", "JSON download",
                       "[entry_time, exit_time)", "half-open interval", "Zero-duration trades",
                       "retained in P&L", "Opposite directions do not cancel gross",
                       "excludes open positions and price changes", "not mark-to-market risk",
                       "margin feasibility", "executable portfolio risk",
                       "not leverage or capital required", "ratios are dimensionless"):
            self.assertIn(phrase, text)
        source = PRODUCT_HTML.read_text(encoding="utf-8").split("const el = id =>")[1].split("</script>", 1)[0]
        for phrase in ("el('exposure-summary').replaceChildren()",
                       "el('exposure-rows').replaceChildren()", "cell.textContent = point[key]",
                       "key === 'profit_factor' ? 'Not defined: no losses'",
                       "No positive-duration trades: no maximum concurrency timestamp",
                       "No positive-duration trades: no maximum gross entry notional timestamp",
                       "report = data", "JSON.stringify(report,null,2)"):
            self.assertIn(phrase, source)
        for unsafe in ("Number(", "parseFloat(", "innerHTML"):
            self.assertNotIn(unsafe, source)

    def test_recovery_document_and_source_contract(self):
        nodes = {n.attrs.get("id"): n for n in self.elements}
        results = nodes["ledger-results"]
        self.assertIn("hidden", results.attrs)
        ids = [n.attrs.get("id") for n in results.elements()]
        for suffix in ("dollar", "percent"):
            self.assertEqual(ids.count("ledger-recovery-" + suffix), 1)
        headings = [n.text() for n in results.elements() if n.tag == "h3"]
        self.assertIn("Largest dollar drawdown recovery", headings)
        self.assertIn("Largest percentage drawdown recovery", headings)
        for phrase in ("realized-balance episodes", "excluding open positions",
                       "mark-to-market changes", "no future-risk claim",
                       "first subsequent balance", "final grouped exit"):
            self.assertIn(phrase, results.text())
        source = PRODUCT_HTML.read_text(encoding="utf-8").split("const el = id =>")[1].split("</script>", 1)[0]
        for phrase in ("el('recovery-dollar').replaceChildren()",
                       "el('recovery-percent').replaceChildren()",
                       "No realized drawdown:", "initial balance has no observed timestamp",
                       "initial balance time is unavailable", "Unrecovered at observation end:",
                       "'observation end (unrecovered)'", "' (seconds)'",
                       "episode[key] === null ? missing[key] : episode[key]",
                       "JSON.stringify(report,null,2)"):
            self.assertIn(phrase, source)
        self.assertLess(source.index("if (current !== version) return;"),
                        source.index("const episode = data.drawdown_recovery[name]"))

    def readiness_section(self):
        targets = [
            node for node in self.elements
            if node.attrs.get('id') == 'research-readiness'
        ]
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].tag, 'section')
        return targets[0]

    def navigation(self):
        navigation = [
            node for node in self.elements
            if node.tag == 'nav' and node.attrs.get('aria-label') == 'Triad'
        ]
        self.assertEqual(len(navigation), 1)
        return navigation[0]

    def test_readiness_entry_uses_local_fragment(self):
        entries = [
            link for link in self.links
            if link.text().strip() == 'Understand research readiness'
        ]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].attrs.get('href'), '#research-readiness')
        self.assertNotIn(
            '/triad/product/research-readiness',
            [link.attrs.get('href') for link in self.links],
        )

    def test_every_nonempty_local_fragment_has_exactly_one_target(self):
        id_counts = Counter(
            node.attrs['id'] for node in self.elements if 'id' in node.attrs
        )
        fragments = [
            link.attrs.get('href') or '' for link in self.links
            if (link.attrs.get('href') or '').startswith('#')
            and len(link.attrs['href']) > 1
        ]
        self.assertIn('#research-readiness', fragments)
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertEqual(id_counts[unquote(fragment[1:])], 1)

    def test_readiness_target_has_heading_and_explanatory_text(self):
        section = self.readiness_section()
        headings = [node for node in section.elements() if node.tag == 'h2']
        self.assertEqual(len(headings), 1)
        self.assertEqual(
            headings[0].text().strip(), 'Understanding research readiness'
        )
        paragraphs = [node for node in section.elements() if node.tag == 'p']
        self.assertTrue(paragraphs)
        self.assertTrue(all(node.text().strip() for node in paragraphs))
        explanation = ' '.join(' '.join(node.text().split()) for node in paragraphs)
        for required_text in (
            'explanatory guidance, not a current readiness assessment',
            'Coverage concerns the requested research scope',
            'Missing evidence concerns what remains necessary under reviewed readiness definitions',
            'Research readiness does not establish strategy edge or real-market performance',
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, explanation)

    def test_existing_product_boundaries_remain_visible(self):
        text = ' '.join(self.document.text().split())
        for required_text in (
            'EARLY PRODUCT',
            'There is no live account, order entry, portfolio management or validated trading strategy here yet.',
            'Existing fixture results verify the research engine; they do not establish real-market readiness or strategy performance.',
            'Data readiness does not establish strategy edge.',
        ):
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, text)

    def test_existing_navigation_destinations_remain(self):
        navigation = self.navigation()
        destinations = {
            (node.text().strip(), node.attrs.get('href'))
            for node in navigation.elements() if node.tag == 'a'
        }
        for expected in (
            ('Development', '/triad/development'),
            ('Cycles', '/triad/cycles'),
            ('Daily Debrief', '/triad/daily-debrief'),
        ):
            with self.subTest(destination=expected):
                self.assertIn(expected, destinations)

    def test_nav_current_page_attribute(self):
        navigation = self.navigation()
        nav_links = {
            node.text().strip(): node
            for node in navigation.elements() if node.tag == 'a'
        }
        self.assertEqual(nav_links['Product'].attrs.get('aria-current'), 'page')
        for label in ('Development', 'Cycles', 'Daily Debrief'):
            with self.subTest(label=label):
                self.assertNotIn('aria-current', nav_links[label].attrs)


    def test_bar_inspection_section_contract(self):
        nodes = {n.attrs.get("id"): n for n in self.elements}
        section = nodes["bar-inspection"]
        self.assertEqual(section.tag, "section")
        self.assertEqual([n.attrs.get("id") for n in self.elements].count("bar-inspection"), 1)
        text = section.text()
        for phrase in (
            "user-supplied",
            "not a market feed",
            "not a chart",
            "not a backtest",
            "not strategy edge",
        ):
            self.assertIn(phrase, text)
        source = PRODUCT_HTML.read_text(encoding="utf-8")
        bar_source = source.split('id="bar-inspection"', 1)[1]
        self.assertIn("/triad/product-api/research/bar-inspection", bar_source)
        self.assertIn(".textContent", bar_source)
        self.assertNotIn("innerHTML", bar_source)


if __name__ == '__main__':
    unittest.main()
