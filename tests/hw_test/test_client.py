"""Unit tests for the JLCPCB Nuxt SSR scraping client."""

import textwrap

from hw.circuits.jlcpcb.bom_lookup.client import (
    _build_param_map,
    _parse_components,
    _parse_nuxt_args,
    _resolve,
    _sanitize_query,
)

# ---------------------------------------------------------------------------
# _parse_nuxt_args
# ---------------------------------------------------------------------------


class TestParseNuxtArgs:
    def test_simple_values(self):
        assert _parse_nuxt_args('"hello",42,true') == ['"hello"', "42", "true"]

    def test_empty_string(self):
        assert _parse_nuxt_args("") == []

    def test_quoted_strings_with_commas(self):
        args = _parse_nuxt_args('"a,b","c"')
        assert args == ['"a,b"', '"c"']

    def test_nested_braces(self):
        args = _parse_nuxt_args('{a:1,b:2},"x"')
        assert args == ["{a:1,b:2}", '"x"']

    def test_escaped_quotes(self):
        args = _parse_nuxt_args(r'"he said \"hi\"",42')
        assert len(args) == 2
        assert args[1] == "42"

    def test_void_0(self):
        args = _parse_nuxt_args("void 0,42")
        assert args == ["void 0", "42"]


# ---------------------------------------------------------------------------
# _build_param_map
# ---------------------------------------------------------------------------


class TestBuildParamMap:
    def test_simple_nuxt_payload(self):
        html = 'window.__NUXT__=(function(a,b,c){return {x:a}}("hello",42,true))'
        pm = _build_param_map(html)
        assert pm["a"] == '"hello"'
        assert pm["b"] == "42"
        assert pm["c"] == "true"

    def test_no_nuxt(self):
        assert _build_param_map("<html></html>") == {}


# ---------------------------------------------------------------------------
# _resolve
# ---------------------------------------------------------------------------


class TestResolve:
    def test_string_literal(self):
        assert _resolve('"hello"', {}) == "hello"

    def test_variable_ref(self):
        assert _resolve("a", {"a": '"world"'}) == "world"

    def test_numeric(self):
        assert _resolve("42", {}) == "42"

    def test_void_0(self):
        assert _resolve("void 0", {}) is None

    def test_none_input(self):
        assert _resolve(None, {}) is None

    def test_variable_to_void(self):
        assert _resolve("x", {"x": "void 0"}) is None


# ---------------------------------------------------------------------------
# _sanitize_query
# ---------------------------------------------------------------------------


class TestSanitizeQuery:
    def test_at_sign(self):
        assert _sanitize_query("120R@100MHz") == "120R 100MHz"

    def test_slash(self):
        assert _sanitize_query("10uF/10V") == "10uF 10V"

    def test_backslash(self):
        assert _sanitize_query("a\\b") == "a b"

    def test_plain(self):
        assert _sanitize_query("100nF") == "100nF"

    def test_multiple_spaces(self):
        assert _sanitize_query("  a @  b  ") == "a b"


# ---------------------------------------------------------------------------
# _parse_components (integration-style with synthetic HTML)
# ---------------------------------------------------------------------------

# Minimal synthetic Nuxt SSR payload with one component record
_SYNTHETIC_HTML = textwrap.dedent(
    """\
    <html><head></head><body>
    <script>window.__NUXT__=(function(a,b,c,d,e){return {data:[{componentPageInfo:{list:[{componentCode:"C1525",componentModelEn:a,componentName:b,stockCount:35787350,componentBrandEn:c,componentSpecificationEn:d,describe:e}]}}]}}("CL05B104KO5NNNC","Samsung CL05B104KO5NNNC","Samsung Electro-Mechanics","0402","100nF cap"))</script>
    </body></html>
"""
)


class TestParseComponents:
    def test_extracts_component(self):
        results = _parse_components(_SYNTHETIC_HTML)
        assert len(results) == 1
        r = results[0]
        assert r.lcsc_part == "C1525"
        assert r.mfr_part == "CL05B104KO5NNNC"
        assert r.stock == 35787350
        assert r.manufacturer == "Samsung Electro-Mechanics"
        assert r.package == "0402"
        assert r.source == "jlcpcb"

    def test_no_components(self):
        html = '<html><script>window.__NUXT__=(function(a){return {}}("x"))</script></html>'
        assert _parse_components(html) == []

    def test_no_nuxt(self):
        assert _parse_components("<html></html>") == []
