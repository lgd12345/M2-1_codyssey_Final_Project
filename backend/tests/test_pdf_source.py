from app.agent_rag.pdf_source import render_pdf_page


def test_page_image_is_rendered_only_on_cache_miss(tmp_path):
    calls = []

    def fake_renderer(_pdf_path, page, dpi):
        calls.append((page, dpi))
        return b"png-rendered-page"

    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"pdf")
    first = render_pdf_page(pdf_path, "a" * 64, 4, 150, cache_dir=tmp_path / "cache", renderer=fake_renderer)
    second = render_pdf_page(pdf_path, "a" * 64, 4, 150, cache_dir=tmp_path / "cache", renderer=fake_renderer)
    assert first == second == b"png-rendered-page"
    assert calls == [(4, 150)]


def test_cache_key_changes_for_page_or_dpi(tmp_path):
    calls = []

    def fake_renderer(_pdf_path, page, dpi):
        calls.append((page, dpi))
        return f"page-{page}-dpi-{dpi}".encode()

    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"pdf")
    cache = tmp_path / "cache"
    render_pdf_page(pdf, "b" * 64, 1, 150, cache_dir=cache, renderer=fake_renderer)
    render_pdf_page(pdf, "b" * 64, 2, 150, cache_dir=cache, renderer=fake_renderer)
    render_pdf_page(pdf, "b" * 64, 1, 200, cache_dir=cache, renderer=fake_renderer)
    assert calls == [(1, 150), (2, 150), (1, 200)]
