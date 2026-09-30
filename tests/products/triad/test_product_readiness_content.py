"""Offline document checks; these do not verify browser navigation or rendering."""

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import unquote


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

    def readiness_section(self):
        targets = [
            node for node in self.elements
            if node.attrs.get('id') == 'research-readiness'
        ]
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].tag, 'section')
        return targets[0]

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
        navigation = [
            node for node in self.elements
            if node.tag == 'nav' and node.attrs.get('aria-label') == 'Triad'
        ]
        self.assertEqual(len(navigation), 1)
        destinations = {
            (node.text().strip(), node.attrs.get('href'))
            for node in navigation[0].elements() if node.tag == 'a'
        }
        for expected in (
            ('Development', '/triad/development'),
            ('Cycles', '/triad/cycles'),
            ('Daily Debrief', '/triad/daily-debrief'),
        ):
            with self.subTest(destination=expected):
                self.assertIn(expected, destinations)


if __name__ == '__main__':
    unittest.main()
