"""London Stock Exchange shares offered through Alpha Vantage's free plan.

Alpha Vantage has no free list of LSE companies, so this is the FTSE 100
(as at 2026, give or take index changes). Codes are Alpha Vantage symbols:
the LSE ticker (EPIC) without any trailing dot, plus ".LON".
Prices are quoted in pence for almost all of these.
"""

FTSE_100: list[tuple[str, str]] = [
    ("AAF", "Airtel Africa"), ("AAL", "Anglo American"), ("ABF", "Associated British Foods"),
    ("ADM", "Admiral Group"), ("ALW", "Alliance Witan"), ("ANTO", "Antofagasta"),
    ("AUTO", "Auto Trader Group"), ("AV", "Aviva"), ("AZN", "AstraZeneca"), ("BA", "BAE Systems"),
    ("BAB", "Babcock International"), ("BARC", "Barclays"), ("BATS", "British American Tobacco"),
    ("BEZ", "Beazley"), ("BKG", "Berkeley Group"), ("BME", "B&M European Value Retail"),
    ("BNZL", "Bunzl"), ("BP", "BP"), ("BT-A", "BT Group"), ("BTRW", "Barratt Redrow"),
    ("CCEP", "Coca-Cola Europacific Partners"), ("CCH", "Coca-Cola HBC"), ("CNA", "Centrica"),
    ("CPG", "Compass Group"), ("CRDA", "Croda International"), ("CTEC", "ConvaTec"),
    ("DCC", "DCC"), ("DGE", "Diageo"), ("DPLM", "Diploma"), ("EDV", "Endeavour Mining"),
    ("ENT", "Entain"), ("EXPN", "Experian"), ("EZJ", "easyJet"), ("FCIT", "F&C Investment Trust"),
    ("FRES", "Fresnillo"), ("GAW", "Games Workshop"), ("GLEN", "Glencore"), ("GSK", "GSK"),
    ("HIK", "Hikma Pharmaceuticals"), ("HLMA", "Halma"), ("HLN", "Haleon"), ("HSBA", "HSBC"),
    ("HSX", "Hiscox"), ("HWDN", "Howden Joinery"), ("IAG", "International Airlines Group (BA)"),
    ("ICG", "Intermediate Capital Group"), ("IGG", "IG Group"), ("IHG", "InterContinental Hotels"),
    ("III", "3i Group"), ("IMB", "Imperial Brands"), ("IMI", "IMI"), ("INF", "Informa"),
    ("ITRK", "Intertek"), ("JD", "JD Sports Fashion"), ("KGF", "Kingfisher"), ("LAND", "Land Securities"),
    ("LGEN", "Legal & General"), ("LLOY", "Lloyds Banking Group"), ("LMP", "LondonMetric Property"),
    ("LSEG", "London Stock Exchange Group"), ("MKS", "Marks & Spencer"), ("MNDI", "Mondi"),
    ("MNG", "M&G"), ("MRO", "Melrose Industries"), ("NG", "National Grid"), ("NWG", "NatWest Group"),
    ("NXT", "Next"), ("PCT", "Polar Capital Technology Trust"), ("PHNX", "Phoenix Group"),
    ("PRU", "Prudential"), ("PSH", "Pershing Square Holdings"), ("PSN", "Persimmon"), ("PSON", "Pearson"),
    ("REL", "RELX"), ("RIO", "Rio Tinto"), ("RKT", "Reckitt Benckiser"), ("RMV", "Rightmove"),
    ("RR", "Rolls-Royce"), ("RTO", "Rentokil Initial"), ("SBRY", "Sainsbury's"), ("SDR", "Schroders"),
    ("SGE", "Sage Group"), ("SGRO", "Segro"), ("SHEL", "Shell"), ("SMIN", "Smiths Group"),
    ("SMT", "Scottish Mortgage Investment Trust"), ("SN", "Smith & Nephew"), ("SPX", "Spirax Group"),
    ("SSE", "SSE"), ("STAN", "Standard Chartered"), ("STJ", "St James's Place"), ("SVT", "Severn Trent"),
    ("TSCO", "Tesco"), ("TW", "Taylor Wimpey"), ("ULVR", "Unilever"), ("UTG", "Unite Group"),
    ("UU", "United Utilities"), ("VOD", "Vodafone"), ("WEIR", "Weir Group"), ("WPP", "WPP"),
    ("WTB", "Whitbread"),
]


def rows() -> list[dict]:
    return [
        {
            "code": f"{epic}.LON",
            "name": name,
            "asset_class": "ukstock",
            "provider": "alphavantage",
            "provider_symbol": f"{epic}.LON",
            "precision": 2,
            "exchange": "LSE",
        }
        for epic, name in FTSE_100
    ]
