import pytest

from yoola.urltools import UrlError, assert_public_host, normalize_url


def test_normalize_strips_tracking_fragment_port_and_case():
    assert (
        normalize_url("HTTPS://Example.COM:443/Terms/?utm_source=x&gclid=1&b=2#s4")
        == "https://example.com/Terms/?b=2"
    )


def test_normalize_preserves_trailing_slash():
    # Stripping it caused redirect ping-pong with sites that 301 to the slash
    # variant; slash twins converge via the content hash instead.
    assert normalize_url("https://example.com/terms/") == "https://example.com/terms/"
    assert normalize_url("https://example.com/terms") == "https://example.com/terms"


def test_normalize_keeps_meaningful_query_and_nondefault_port():
    assert normalize_url("http://example.com:8080/t?lang=en") == "http://example.com:8080/t?lang=en"


def test_normalize_root_path():
    assert normalize_url("https://example.com") == "https://example.com/"


@pytest.mark.parametrize("bad", ["ftp://example.com/x", "javascript:alert(1)", "not a url"])
def test_normalize_rejects_non_http(bad):
    with pytest.raises(UrlError):
        normalize_url(bad)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/terms",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
    ],
)
def test_ssrf_guard_rejects_private_hosts(url):
    with pytest.raises(UrlError):
        assert_public_host(url)
