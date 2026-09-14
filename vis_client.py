"""
vis_client.py
--------------
Thin HTTP client for the FIVB VIS XML API.

IMPORTANT: I do not have a live VIS credential to test against from this
environment (no network access to fivb.org here), so this client is built
from the FIVB VIS API's publicly documented calling convention:

    GET https://www.fivb.org/Vis2009/XmlRequest.asmx?Request=<url-encoded XML>

with HTTP Basic Authentication (username/password) on the request.

If your credential/documentation shows a different auth style (e.g. an
"X-FIVB-App-ID" header, or username/password embedded as XML attributes on
the <Request> element itself), change `_send_request()` below - everything
else in this project (parsers, scoring engine, exporter) is independent of
this detail. Use the "Test connection" button in the Streamlit app to check
this against your real credentials before relying on the tool.
"""

import requests
from typing import Optional

VIS_BASE_URL = "https://www.fivb.org/Vis2009/XmlRequest.asmx"


class VisClient:
    def __init__(self, username: str, password: str, base_url: str = VIS_BASE_URL,
                 auth_style: str = "basic"):
        self.username = username
        self.password = password
        self.base_url = base_url
        self.auth_style = auth_style  # "basic" or "embedded"

    def _send_request(self, request_xml: str) -> str:
        params = {"Request": request_xml}
        auth = None
        if self.auth_style == "basic":
            auth = (self.username, self.password)
        elif self.auth_style == "embedded":
            # some VIS deployments expect Login/Password as attributes on
            # the <Request> tag itself instead of HTTP Basic Auth.
            request_xml = request_xml.replace(
                "<Request ",
                f'<Request Login="{self.username}" Password="{self.password}" ',
                1,
            )
            params = {"Request": request_xml}

        resp = requests.get(self.base_url, params=params, auth=auth, timeout=30)
        if not resp.ok:
            # Surface VIS's actual error body instead of a bare "400 Bad Request" -
            # it usually names exactly which attribute/filter it didn't like.
            raise RuntimeError(
                f"VIS returned HTTP {resp.status_code} for request:\n{request_xml}\n\n"
                f"Response body:\n{resp.text[:2000]}"
            )
        return resp.text

    def test_connection(self) -> bool:
        """Minimal call to verify credentials work. Returns True/raises on failure."""
        # Deliberately no Filter here - just prove auth + basic request shape work
        # before layering on filter syntax we haven't been able to verify live.
        xml = '<Request Type="GetBeachTournamentList" Fields="Code Name Season"/>'
        text = self._send_request(xml)
        return "<BeachTournament" in text or "<Responses" in text

    # ------------------------------------------------------------------
    # Domain calls
    # ------------------------------------------------------------------

    def get_tournament_list(self, season_from: int, season_to: int,
                             filter_xml: Optional[str] = None) -> str:
        """
        Returns raw XML text - pass to vis_parser.parse_tournament_list().

        NOTE: the season_from/season_to args are currently unused - the
        Filter syntax for restricting by season is another guess I haven't
        been able to verify live (same issue as test_connection had). This
        pulls the FULL tournament list unfiltered for now, which is slower
        but guaranteed not to 400 on a bad filter. Once you see what a
        *working* filtered request looks like (e.g. from VIS support docs,
        or by trial and error), pass it in via filter_xml and I'll wire the
        season_from/season_to args back in properly.
        """
        fields = ('Fields="No Code Name Season Type OrganizerCode CountryCode '
                  'StartDateMainDraw EndDateMainDraw Gender"')
        filt = f' Filter="{filter_xml}"' if filter_xml else ""
        xml = f'<Request Type="GetBeachTournamentList" {fields}{filt}/>'
        return self._send_request(xml)

    def _send_batch(self, request_xmls: list) -> str:
        envelope = "<Requests>" + "".join(request_xmls) + "</Requests>"
        return self._send_request(envelope)

    def get_tournament_entry_list(self, tournament_no_or_code: str) -> str:
        """Returns raw XML text for one event + its team list.
        pass to vis_parser.parse_tournament_entry_list().

        Attempt #3 - based on the actual working request you shared:
        the team list is a SEPARATE `GetBeachTeamList` call filtered by
        `NoTournament`, with `<Relation Name="Player1"/">`/`Player2` (not
        nested `<BeachTeams>`/dot-paths as I'd guessed before) to pull in
        player names. Batched together with the GetBeachTournament call.
        """
        value = tournament_no_or_code.strip()
        if not value.isdigit():
            raise ValueError(
                f"get_tournament_entry_list needs a numeric VIS 'No', got '{value}'. "
                f"Use resolve_tournament_no(code, tournament_list) first."
            )
        event_req = (
            f'<Request Type="GetBeachTournament" No="{value}" '
            f'Fields="Code Name Type OrganizerCode CountryCode StartDateMainDraw '
            f'EndDateMainDraw EntryPointsDayOffset SeedPointsDayOffset Gender"/>'
        )
        team_req = (
            f'<Request Type="GetBeachTeamList" '
            f'Fields="No NoPlayer1 NoPlayer2 Name FederationCode Status '
            f'PositionInMainDraw PositionInReserve PositionInQualification PositionInEntry">'
            f'<Filter NoTournament="{value}"/>'
            f'<Relation Name="Player1" Fields="No FirstName LastName"/>'
            f'<Relation Name="Player2" Fields="No FirstName LastName"/>'
            f'</Request>'
        )
        return self._send_batch([event_req, team_req])

    def get_player_career(self, player_no: str) -> str:
        """Returns raw XML text - pass to vis_parser.parse_player_career().

        Same fix as get_tournament_entry_list: a separate GetBeachTeamList
        call, this time filtered by NoPlayer (my best guess for "either
        Player1 or Player2 == this player" - unconfirmed, flag it if VIS
        rejects this filter name and we'll adjust), batched with GetPlayer.
        """
        player_req = (
            f'<Request Type="GetPlayer" No="{player_no}" '
            f'Fields="NO FIRSTNAME LASTNAME CONFEDERATIONCODE COUNTRYCODE FEDERATIONCODE"/>'
        )
        team_req = (
            f'<Request Type="GetBeachTeamList" '
            f'Fields="NoPlayer1 NoPlayer2 Player1FirstName Player1LastName '
            f'Player2FirstName Player2LastName TournamentCode TournamentName '
            f'TournamentSeason TournamentEndDateMainDraw TournamentType Rank '
            f'EarnedPointsPlayer CountryCode Status">'
            f'<Filter NoPlayer="{player_no}"/>'
            f'</Request>'
        )
        return self._send_batch([player_req, team_req])

    def get_avc_country_codes(self) -> set:
        """
        Query all National Federations and return the set of 2-letter country
        codes whose ConfederationCode == 'AVC'. Used for the "multi-sport game
        hosted in an AVC country" check, so we never have to hand-maintain the
        65-federation list.
        """
        xml = (
            '<Request Type="GetFederationList" '
            'Fields="Code Name ConfederationCode Country"/>'
        )
        text = self._send_request(xml)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        codes = set()
        for fed in root.iter("Federation"):
            if (fed.get("ConfederationCode") or "").upper() == "AVC":
                c = fed.get("Country") or fed.get("Code")
                if c:
                    codes.add(c.upper())
        return codes
