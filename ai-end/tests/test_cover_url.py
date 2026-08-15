from app.config import build_cover_url, extract_cover_source_name, is_safe_cover_source_name


class TestCoverUrl:
    def test_relative_path_becomes_proxy(self):
        url = build_cover_url("cover/a.jpg")
        assert url.startswith("/ai/media/cover?sourceName=")
        assert "cover/a.jpg" in url

    def test_gateway_get_resource_url_rewritten(self):
        raw = "http://gateway:8080/api/file/getResource?sourceName=cover/foo.png"
        url = build_cover_url(raw)
        assert url.startswith("/ai/media/cover?")
        assert "cover/foo.png" in url
        assert "gateway" not in url

    def test_public_cdn_passthrough(self):
        cdn = "https://cdn.example.com/covers/a.jpg"
        assert build_cover_url(cdn) == cdn

    def test_empty(self):
        assert build_cover_url("") == ""
        assert extract_cover_source_name("") == ""

    def test_reject_path_traversal(self):
        assert not is_safe_cover_source_name("../etc/passwd")
        assert build_cover_url("../etc/passwd") == ""

    def test_reject_ssrf_url_as_source(self):
        assert not is_safe_cover_source_name("http://evil.com/x")
        assert not is_safe_cover_source_name("//evil.com/x")
