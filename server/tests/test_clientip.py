from yoola.clientip import client_ip, reporter_hash


def test_direct_uses_socket_peer():
    assert client_ip("203.0.113.7", "1.2.3.4", trusted_hops=0) == "203.0.113.7"
    assert client_ip("203.0.113.7", None, trusted_hops=0) == "203.0.113.7"


def test_one_trusted_hop_reads_last_forwarded_entry():
    # Our proxy appends the real peer; a client-injected leading entry is ignored.
    assert client_ip("127.0.0.1", "9.9.9.9, 203.0.113.7", trusted_hops=1) == "203.0.113.7"
    assert client_ip("127.0.0.1", "203.0.113.7", trusted_hops=1) == "203.0.113.7"


def test_two_trusted_hops():
    assert client_ip("127.0.0.1", "203.0.113.7, cdn, edge", trusted_hops=2) == "cdn"


def test_falls_back_when_chain_too_short():
    assert client_ip("127.0.0.1", "", trusted_hops=1) == "127.0.0.1"


def test_reporter_hash_is_stable_and_salted():
    assert reporter_hash("1.2.3.4", "salt") == reporter_hash("1.2.3.4", "salt")
    assert reporter_hash("1.2.3.4", "salt") != reporter_hash("1.2.3.4", "other")
    assert reporter_hash("1.2.3.4", "salt") != reporter_hash("1.2.3.5", "salt")
