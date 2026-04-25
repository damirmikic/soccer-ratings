import unittest

from soccer_ratings.client import build_league_mode_url
from soccer_ratings.parser import (
    parse_leagues,
    parse_rankings,
    parse_special_rating_links,
    parse_team_history_matches,
    parse_team_ratings,
)


SAMPLE_HTML = """
<div class="content2" style="border:0px solid">
<table bgcolor="#ffffff" width="300" class="bigtable" cellpadding="3" cellspacing="0">
<tbody>
<tr style="background-color:#006600;background-image:url(/images/gradient.png);" height="22">
<th><font color="#ffffff" size="2" face="Verdana">&nbsp;<b>UEFA League Ranking</b></font></th>
<td><font color="#ffffff" size="2" face="Verdana"><b>Rating</b></font></td>
</tr>
<tr><td><img src="/flags/UK.gif" width="28" height="19"> <a href="/England/">England</a></td><td>2429.79</td></tr>
<tr><td><img src="/flags/DE.gif" width="28" height="19"> <a href="/Germany/">Germany</a></td><td>2359.21</td></tr>
</tbody>
</table><p></p></div>
<div class="content2" style="border:0px solid">
<table bgcolor="#ffffff" width="300" class="bigtable" cellpadding="3" cellspacing="0">
<tbody>
<tr style="background-color:#006600;background-image:url(/images/gradient.png);" height="22">
<th><font color="#ffffff" size="2" face="Verdana">&nbsp;<b>UEFA League Ranking</b></font></th>
<td><font color="#ffffff" size="2" face="Verdana"><b>Rating</b></font></td>
</tr>
<tr><td><img src="/flags/CS.gif" width="28" height="19"> <a href="/Serbia/">Serbia</a></td><td>1881.94</td></tr>
<tr><td><img src="/flags/FA.gif" width="28" height="19"> <a href="/Faeroeer/">Färöer</a></td><td>1633.53</td></tr>
</tbody>
</table><p></p></div>
"""


class ParseRankingsTests(unittest.TestCase):
    def test_parse_rankings_collects_rows_across_multiple_tables(self) -> None:
        rankings = parse_rankings(SAMPLE_HTML)

        self.assertEqual(len(rankings), 4)
        self.assertEqual(rankings[0].country, "England")
        self.assertEqual(rankings[0].rating, 2429.79)
        self.assertEqual(rankings[0].country_path, "/England/")
        self.assertEqual(rankings[2].rank, 3)
        self.assertEqual(rankings[2].country, "Serbia")

    def test_parse_rankings_preserves_unicode_names(self) -> None:
        rankings = parse_rankings(SAMPLE_HTML)

        self.assertEqual(rankings[3].country, "Färöer")


LEAGUES_HTML = """
<div class="content2" style="border:0px solid;">
<table bgcolor="#ffffff" width="350" class="bigtable rattab">
<tbody>
<tr><th bgcolor="#006600" colspan="4" height="22" style="padding-left:6px"><font color="#ffffff" face="Verdana" size="2"><b>Leagues Average Rating</b></font></th></tr>
<tr><td>1.</td><td><a href="/England/">Premier League</a></td><td><img src="/flags/UK.gif" width="28" height="19"></td><td>2313.46</td></tr>
<tr><td>2.</td><td><a href="/England/UK2/">Championship</a></td><td><img src="/flags/UK.gif" width="28" height="19"></td><td>2032.31</td></tr>
</tbody></table><p></p>
<div class="special">
<table bgcolor="#ffffff" width="350" class="bigtable rattab">
<tbody>
<tr><th bgcolor="#006600" colspan="2" height="22" style="padding-left:6px"><font color="#ffffff" face="Verdana" size="2"><b>Special Ratings</b></font></th></tr>
<tr><td><a href="/England/UK1/home/" rel="nofollow">Home Ratings</a></td></tr>
<tr><td><a href="/England/UK1/away/" rel="nofollow">Away Ratings</a></td></tr>
<tr><td><a href="/England/UK1/">General Ratings</a></td></tr>
</tbody></table></div></div>
"""


TEAM_RATINGS_HTML = """
<div class="content2" style="border:0px solid">
<table bgcolor="#ffffff" width="350" class="bigtable rattab">
<tbody>
<tr><th>Pos</th><th>Team</th><th>League</th><th>Flag</th><th>Rating</th></tr>
<tr><td>1.</td><td><a href="/England/Manchester-City/">Manchester City</a></td><td>UK1</td><td><img src="/flags/UK.gif"></td><td>2488.12</td></tr>
<tr><td>2.</td><td><a href="/England/Arsenal/">Arsenal</a></td><td>UK1</td><td><img src="/flags/UK.gif"></td><td>2410.55</td></tr>
</tbody></table>
<table bgcolor="#ffffff" width="350" class="bigtable rattab">
<tbody>
<tr><th>Pos</th><th>League</th><th>Flag</th><th>Rating</th></tr>
<tr><td>1.</td><td><a href="/Italy/IT1/">Serie A</a></td><td><img src="/flags/IT.gif"></td><td>2190.43</td></tr>
<tr><td>2.</td><td><a href="/Italy/IT2/">Serie B</a></td><td><img src="/flags/IT.gif"></td><td>1887.80</td></tr>
</tbody></table></div>
"""


TEAM_HISTORY_HTML = """
<div class="content2 leftc" style="border:0px solid;max-width:100%">
<table class="bigtable" bgcolor="#ffffff" width="100%" cellspacing="0" cellpadding="3" border="0">
<tbody>
<tr>
<td bgcolor="#006600"></td>
<td bgcolor="#006600"><b>Matches</b></td>
<td bgcolor="#006600"><b>Borac Banja Luka</b></td>
<th bgcolor="#006600"><b>1</b></th>
<th bgcolor="#006600"><b>X</b></th>
<th bgcolor="#006600"><b>2</b></th>
<th bgcolor="#006600"><b>Odds</b></th>
<td bgcolor="#006600"><b></b></td>
<th bgcolor="#006600" colspan="2"><b>Home/Away</b></th>
<td bgcolor="#006600"><b>Res.</b></td>
</tr>
<tr bgcolor="#ffffff"><td class="nomobil">30</td><td>26.04.26<div class="ismobil">BA1</div></td><td><b>Borac Banja Luka</b> <font color="#ff0000">↓</font> - <a href="/FK-Sloga-Doboj/19154/" class="list"><b>FK Sloga Doboj</b></a></td><td align="center" class="nomobil">1.17</td><td align="center" class="nomobil">6.00</td><td align="center" class="nomobil">12.50</td><td class="ismobil">1.17<br>6.00<br>12.50</td><td class="nomobil">BA1</td><td><b>1986.19</b></td><td>1598.55</td><td></td></tr>
<tr bgcolor="#f3f3f3"><td class="nomobil">29</td><td>22.04.26<div class="ismobil">BA1</div></td><td><a href="/Zrinjski-Mostar/536/" class="list">Zrinjski Mostar</a> - Borac Banja Luka</td><td align="center" class="nomobil">2.60</td><td align="center" class="nomobil"><b>2.65</b></td><td align="center" class="nomobil">2.75</td><td class="ismobil">2.60<br><b>2.65</b><br>2.75</td><td class="nomobil">BA1</td><td>1905.69</td><td><b>1986.19</b></td><td>1:1</td></tr>
</tbody></table></div>
"""


class ParseLeagueTests(unittest.TestCase):
    def test_parse_leagues_ignores_special_rating_links(self) -> None:
        leagues = parse_leagues(LEAGUES_HTML)

        self.assertEqual(len(leagues), 2)
        self.assertEqual(leagues[0].league, "Premier League")
        self.assertEqual(leagues[0].league_path, "/England/")
        self.assertEqual(leagues[1].rank, 2)
        self.assertEqual(leagues[1].rating, 2032.31)

    def test_parse_special_rating_links_reads_explicit_home_and_away_urls(self) -> None:
        links = parse_special_rating_links(LEAGUES_HTML)

        self.assertEqual(links.general, "/England/UK1/")
        self.assertEqual(links.home, "/England/UK1/home/")
        self.assertEqual(links.away, "/England/UK1/away/")


class ParseTeamRatingsTests(unittest.TestCase):
    def test_parse_team_ratings_for_home_or_away_pages(self) -> None:
        ratings = parse_team_ratings(TEAM_RATINGS_HTML, mode="home")

        self.assertEqual(len(ratings), 2)
        self.assertEqual(ratings[0].rank, 1)
        self.assertEqual(ratings[0].team, "Manchester City")
        self.assertEqual(ratings[0].rating, 2488.12)
        self.assertEqual(ratings[0].team_path, "/England/Manchester-City/")
        self.assertEqual(ratings[0].mode, "home")
        self.assertEqual(ratings[1].team, "Arsenal")


class ParseTeamHistoryTests(unittest.TestCase):
    def test_parse_team_history_matches_extracts_home_and_away_rows(self) -> None:
        matches = parse_team_history_matches(TEAM_HISTORY_HTML)

        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0].focal_team, "Borac Banja Luka")
        self.assertEqual(matches[0].date, "26.04.26")
        self.assertEqual(matches[0].competition, "BA1")
        self.assertEqual(matches[0].home_team, "Borac Banja Luka")
        self.assertEqual(matches[0].away_team, "FK Sloga Doboj")
        self.assertEqual(matches[0].home_odds, 1.17)
        self.assertEqual(matches[0].home_rating, 1986.19)
        self.assertIsNone(matches[0].home_goals)
        self.assertEqual(matches[1].home_team, "Zrinjski Mostar")
        self.assertEqual(matches[1].away_team, "Borac Banja Luka")
        self.assertEqual(matches[1].home_goals, 1)
        self.assertEqual(matches[1].away_goals, 1)


class LeagueUrlBuilderTests(unittest.TestCase):
    def test_build_league_mode_url_supports_home_and_away(self) -> None:
        self.assertEqual(
            build_league_mode_url("/England/UK1/", "home"),
            "https://www.soccer-rating.com/England/UK1/home/",
        )
        self.assertEqual(
            build_league_mode_url("/England/UK1/", "away"),
            "https://www.soccer-rating.com/England/UK1/away/",
        )


if __name__ == "__main__":
    unittest.main()
