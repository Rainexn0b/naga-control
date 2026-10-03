import json
from dataclasses import FrozenInstanceError
from email.message import Message
from http.client import IncompleteRead
from io import BytesIO
from unittest.mock import MagicMock
from urllib import error, request

import pytest
from packaging.version import Version

from naga_control.gui import releases
from naga_control.gui.releases import (
    Release,
    UpdateCheckError,
    fetch_releases,
    installed_version,
    latest_release,
    parse_releases,
)


def entry(tag: str, *, prerelease: bool = False, draft: bool = False) -> dict[str, object]:
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "html_url": "https://untrusted.example/download",
    }


class Response(BytesIO):
    def __init__(self, payload: object = None, *, body: bytes | None = None, link: str = ""):
        super().__init__(json.dumps(payload).encode() if body is None else body)
        self.headers = Message()
        self.headers["Link"] = link
        self.read_sizes: list[int | None] = []

    def read(self, size: int | None = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


@pytest.fixture(autouse=True)
def urlopen(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(spec=request.urlopen, side_effect=AssertionError("Unexpected HTTP request"))
    monkeypatch.setattr(releases.request, "urlopen", mock)
    return mock


@pytest.mark.parametrize("missing", [False, True])
def test_installed_version(monkeypatch: pytest.MonkeyPatch, missing: bool) -> None:
    mock = MagicMock(return_value="0.2.0")
    if missing:
        mock.side_effect = releases.metadata.PackageNotFoundError("naga-control")
    monkeypatch.setattr(releases.metadata, "version", mock)

    assert installed_version() == ("unknown" if missing else "0.2.0")
    mock.assert_called_once_with("naga-control")


def test_release_is_frozen() -> None:
    release = parse_releases([entry("v0.4.0")])[0]
    assert release == Release(
        "v0.4.0",
        Version("0.4.0"),
        False,
        "https://github.com/Rainexn0b/naga-control/releases/tag/v0.4.0",
    )
    with pytest.raises(FrozenInstanceError):
        release.__setattr__("tag", "v99")


@pytest.mark.parametrize(
    ("tag", "flag", "expected"),
    [
        ("v0.4.0", False, False),
        ("0.5.0", True, True),
        ("v0.4.0-rc.1", False, True),
        ("v0.4.0.dev1", False, True),
        ("v0.4.0a1", False, True),
        ("v0.4.0b1", False, True),
        ("v0.4.0.post1", False, False),
        ("v0.4.0+local", False, False),
    ],
)
def test_prerelease_classification(tag: str, flag: bool, expected: bool) -> None:
    release = parse_releases([entry(tag, prerelease=flag)])[0]
    assert release.version == Version(tag.removeprefix("v"))
    assert release.prerelease is expected


def test_canonical_url_ignores_untrusted_html_url_and_encodes_tag() -> None:
    release = parse_releases([entry("v0.4.0+local")])[0]
    assert release.url == "https://github.com/Rainexn0b/naga-control/releases/tag/v0.4.0%2Blocal"


def test_drafts_and_invalid_tags_are_omitted() -> None:
    assert (
        parse_releases(
            [entry("v99", draft=True), entry("not-a-version"), entry(""), entry("../../v0.4.0")]
        )
        == ()
    )
    assert parse_releases([]) == ()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        "[]",
        {"message": "failure"},
        [None],
        ["v1"],
        [{}],
        [{"draft": "false"}],
        [{"draft": False, "tag_name": 1, "prerelease": False}],
        [{"draft": False, "tag_name": "v1", "prerelease": "false"}],
        [{"draft": False, "tag_name": "v1"}],
    ],
)
def test_malformed_release_lists_raise(payload: object) -> None:
    with pytest.raises(UpdateCheckError, match="invalid"):
        parse_releases(payload)


def test_latest_uses_version_not_api_or_date_order() -> None:
    candidates = parse_releases(
        [entry("v0.9.0"), entry("v0.11.0"), entry("v0.10.0"), entry("v0.12.0", prerelease=True)]
    )
    assert latest_release(candidates) == candidates[1]
    assert latest_release(candidates, include_prereleases=True) == candidates[3]


def test_final_rc_dev_ordering() -> None:
    candidates = parse_releases([entry("v0.4.0-rc.1"), entry("v0.4.0"), entry("v0.4.0.dev1")])
    assert latest_release(candidates, include_prereleases=True) == candidates[1]
    assert latest_release((candidates[2], candidates[0]), include_prereleases=True) == candidates[0]
    assert latest_release((candidates[2], candidates[0])) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_stable_flag_wins_equal_versions(reverse: bool) -> None:
    candidates = parse_releases([entry("v0.4.0", prerelease=True), entry("0.4.0")])
    stable = candidates[1]
    if reverse:
        candidates = tuple(reversed(candidates))
    assert latest_release(candidates, include_prereleases=True) == stable
    assert latest_release(candidates) == stable


def test_no_releases_or_only_prereleases() -> None:
    assert latest_release(()) is None
    assert latest_release((), include_prereleases=True) is None
    assert latest_release(parse_releases([entry("v0.4.0", prerelease=True)])) is None


def test_fetch_request_contract_and_bounded_read(urlopen: MagicMock) -> None:
    response = Response([entry("v0.4.0")])
    urlopen.side_effect = [response]
    assert fetch_releases() == parse_releases([entry("v0.4.0")])
    query = urlopen.call_args.args[0]
    assert isinstance(query, request.Request)
    assert query.full_url == (
        "https://api.github.com/repos/Rainexn0b/naga-control/releases?per_page=100&page=1"
    )
    assert query.get_method() == "GET"
    assert {name.lower(): value for name, value in query.header_items()} == {
        "accept": "application/vnd.github+json",
        "user-agent": "Naga-Control",
        "x-github-api-version": "2022-11-28",
    }
    assert urlopen.call_args.kwargs == {"timeout": 5}
    assert response.read_sizes == [2 * 1024 * 1024 + 1]
    assert response.closed


def test_empty_fetch_is_success(urlopen: MagicMock) -> None:
    urlopen.side_effect = [Response([])]
    assert fetch_releases() == ()
    assert urlopen.call_count == 1


@pytest.mark.parametrize("link", ["", '<https://external.example/?page=99>; rel="next"'])
def test_pagination_counts_raw_entries_and_never_follows_external_urls(
    urlopen: MagicMock, link: str
) -> None:
    first = Response([entry("invalid")] * 100, link=link)
    second = Response([entry("v0.11.0"), entry("v0.10.0")])
    urlopen.side_effect = [first, second]
    result = fetch_releases()
    assert result == parse_releases([entry("v0.11.0"), entry("v0.10.0")])
    assert all(response.closed for response in (first, second))
    assert [call.args[0].full_url for call in urlopen.call_args_list] == [
        f"https://api.github.com/repos/Rainexn0b/naga-control/releases?per_page=100&page={page}"
        for page in (1, 2)
    ]


def test_link_next_on_short_page_is_honored(urlopen: MagicMock) -> None:
    urlopen.side_effect = [
        Response([entry("v0.3.0")], link='<https://api.github.com/ignored>; rel="next"'),
        Response([entry("v0.2.0")], link='<https://api.github.com/ignored>; rel="prev"'),
    ]
    assert fetch_releases() == parse_releases([entry("v0.3.0"), entry("v0.2.0")])
    assert urlopen.call_count == 2


def test_three_pages_can_complete(urlopen: MagicMock) -> None:
    urlopen.side_effect = [
        Response([entry("v0.3.0")] * 100),
        Response([entry("v0.2.0")] * 100),
        Response([entry("v0.4.0")]),
    ]
    result = fetch_releases()
    assert len(result) == 201
    assert latest_release(result) == result[-1]
    assert urlopen.call_count == 3


@pytest.mark.parametrize("full_page", [False, True])
def test_truncated_max_pages_fail_closed(urlopen: MagicMock, full_page: bool) -> None:
    responses = [
        Response(
            [entry("v0.4.0")] * (100 if full_page else 1),
            link="" if full_page else '<https://api.github.com/ignored>; rel="next"',
        )
        for _ in range(3)
    ]
    urlopen.side_effect = responses
    with pytest.raises(UpdateCheckError, match=r"3-page.*incomplete"):
        fetch_releases()
    assert urlopen.call_count == 3
    assert all(response.closed for response in responses)


@pytest.mark.parametrize(
    ("code", "message"),
    [(403, "rate limit"), (429, "rate limit"), (404, "not found"), (500, "HTTP 500")],
)
def test_http_errors_are_friendly(urlopen: MagicMock, code: int, message: str) -> None:
    body = BytesIO(b"untrusted error body")
    failure = error.HTTPError("https://api.github.com/", code, "error", Message(), body)
    urlopen.side_effect = failure
    with pytest.raises(UpdateCheckError, match=message) as caught:
        fetch_releases()
    assert caught.value.__cause__ is failure
    assert body.closed


@pytest.mark.parametrize(
    "failure", [error.URLError("offline"), TimeoutError(), OSError("offline"), IncompleteRead(b"")]
)
def test_network_errors_are_friendly(urlopen: MagicMock, failure: Exception) -> None:
    urlopen.side_effect = failure
    with pytest.raises(UpdateCheckError, match="network connection") as caught:
        fetch_releases()
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("body", [b"not JSON", b"[", b"\xff", b"[" * 2000])
def test_malformed_json_raises(urlopen: MagicMock, body: bytes) -> None:
    response = Response(body=body)
    urlopen.side_effect = [response]
    with pytest.raises(UpdateCheckError, match="malformed release JSON"):
        fetch_releases()
    assert response.closed


@pytest.mark.parametrize("payload", [{"message": "error"}, [entry("v0.4.0"), None]])
def test_invalid_full_response_raises(urlopen: MagicMock, payload: object) -> None:
    urlopen.side_effect = [Response(payload)]
    with pytest.raises(UpdateCheckError, match="invalid"):
        fetch_releases()


def test_failure_on_later_page_does_not_return_partial_releases(urlopen: MagicMock) -> None:
    urlopen.side_effect = [Response([entry("v0.4.0")] * 100), error.URLError("offline")]
    with pytest.raises(UpdateCheckError, match="network"):
        fetch_releases()
    assert urlopen.call_count == 2


def test_response_size_limit(urlopen: MagicMock) -> None:
    response = Response(body=b" " * (2 * 1024 * 1024) + b"[]")
    urlopen.side_effect = [response]
    with pytest.raises(UpdateCheckError, match="2 MB"):
        fetch_releases()
    assert response.read_sizes == [2 * 1024 * 1024 + 1]
    assert response.closed


def test_exact_size_limit_is_accepted(urlopen: MagicMock) -> None:
    urlopen.side_effect = [Response(body=b"[]" + b" " * (2 * 1024 * 1024 - 2))]
    assert fetch_releases() == ()


def test_oversized_page_is_invalid(urlopen: MagicMock) -> None:
    urlopen.side_effect = [Response([entry("v0.4.0")] * 101)]
    with pytest.raises(UpdateCheckError, match="page size"):
        fetch_releases()
