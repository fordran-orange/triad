"""Offline structural checks for the product page's readiness explanation."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


PRODUCT_HTML = (
    Path(__file__).resolve().parents[3]
    / 'app/products/triad/static/product.html'
)


class Element:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []

    def text(self):
        return ''.join(
            child if isinstance(child, str) else child.text()
            for child in self.children
        )

    def descendants(self):
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()


class ProductParser(HTMLParser):
    VOID_TAGS = frozenset({
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    })

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element('document')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs, self.stack[-1])
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
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


class ProductReadinessNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parser = ProductParser()
        parser.feed(PRODUCT_HTML.read_text(encoding='utf-8'))
        parser.close()
        cls.elements = list(parser.root.descendants())

    @staticmethod
    def normalized_text(element):
        return ' '.join(element.text().split())

    def readiness_section(self):
        matches = [
            element for element in self.elements
            if element.attrs.get('id') == 'research-readiness'
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].tag, 'section')
        return matches[0]

    def test_readiness_link_resolves_to_unique_local_section(self):
        anchors = [element for element in self.elements if element.tag == 'a']
        links = [
            anchor for anchor in anchors
            if self.normalized_text(anchor) == 'Research Readiness'
        ]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].attrs.get('href'), '#research-readiness')
        section = self.readiness_section()
        self.assertEqual(links[0].attrs['href'][1:], section.attrs['id'])
        self.assertFalse(any(
            anchor.attrs.get('href') == '/triad/product/research-readiness'
            for anchor in anchors
        ))

    def test_readiness_heading_association_resolves_within_section(self):
        section = self.readiness_section()
        self.assertEqual(
            section.attrs.get('aria-labelledby'), 'research-readiness-title'
        )
        headings = [
            element for element in self.elements
            if element.attrs.get('id') == section.attrs['aria-labelledby']
        ]
        self.assertEqual(len(headings), 1)
        heading = headings[0]
        self.assertEqual(heading.tag, 'h2')
        self.assertIn(heading, list(section.descendants()))
        self.assertEqual(self.normalized_text(heading), 'Research Readiness')

    def test_readiness_explanation_preserves_both_limits(self):
        section = self.readiness_section()
        paragraphs = [
            self.normalized_text(element) for element in section.descendants()
            if element.tag == 'p'
        ]
        self.assertEqual(paragraphs, [
            'Research readiness concerns requested coverage and missing evidence '
            'against reviewed readiness definitions. It does not establish '
            'strategy edge or real-market readiness.',
            'This page explains readiness; it does not display a current '
            'readiness assessment or measured coverage.',
        ])

    def test_readiness_section_follows_current_state_as_sibling(self):
        headings = [
            element for element in self.elements
            if element.tag == 'h2'
            and self.normalized_text(element) == 'Current state'
        ]
        self.assertEqual(len(headings), 1)
        current_state = headings[0].parent
        self.assertEqual(current_state.tag, 'section')
        section = self.readiness_section()
        self.assertIs(section.parent, current_state.parent)
        siblings = [
            child for child in section.parent.children
            if isinstance(child, Element)
        ]
        self.assertEqual(siblings.index(section), siblings.index(current_state) + 1)

    def test_existing_early_product_notice_and_limitations_remain(self):
        paragraphs = [element for element in self.elements if element.tag == 'p']
        self.assertTrue(any(
            self.normalized_text(element) == 'EARLY PRODUCT'
            and 'status' in element.attrs.get('class', '').split()
            for element in paragraphs
        ))
        self.assertIn(
            'The product surface is being built. There is no live account, '
            'order entry, portfolio management or validated trading strategy '
            'here yet.',
            [self.normalized_text(element) for element in paragraphs],
        )


if __name__ == '__main__':
    unittest.main()
