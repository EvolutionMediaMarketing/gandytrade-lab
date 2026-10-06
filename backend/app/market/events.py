"""Major market-moving events since 2008, for market replay.

Each event is dated to the first trading day markets could react (news over a weekend is dated to the Monday),
says what happened that day and nothing about what followed (so replay never spoils what comes next), and is
tagged with the kinds of market it mainly affected. A market sees an event when they share a tag; "all" reaches
every market.

Tags: all · equities, us_equities, uk_equities, eu_equities, japan · usd, gbp, eur, jpy, chf, aud, cny ·
gold, silver, metals · oil, gas, energy · grains

Information only: events explain moves after the fact; they are never trade signals.
"""

from datetime import datetime, timezone

from ..market.symbols import Symbol

EVENTS: list[tuple[str, str, str, tuple[str, ...]]] = [
    # (date, title, what happened, tags)
    ("2008-01-22", "Fed makes an emergency rate cut", "After global shares fell sharply, the US Federal Reserve cut interest rates by 0.75% between its scheduled meetings, the biggest single cut in over two decades.", ("equities", "usd")),
    ("2008-03-17", "Bear Stearns rescued", "Over the weekend the US investment bank Bear Stearns, close to collapse, agreed to be bought by JPMorgan with Federal Reserve backing.", ("equities", "usd", "gold")),
    ("2008-07-11", "Oil hits a record high", "Oil traded above $147 a barrel, a record, amid tight supply and a weak dollar.", ("oil", "energy")),
    ("2008-09-08", "US takes over Fannie Mae and Freddie Mac", "Over the weekend the US government took control of the two giant mortgage firms to stop them failing.", ("equities", "usd")),
    ("2008-09-15", "Lehman Brothers collapses", "The US investment bank Lehman Brothers filed for bankruptcy, the largest in US history, and Merrill Lynch agreed to be sold to Bank of America.", ("all",)),
    ("2008-09-29", "US Congress rejects the bank bailout", "The House of Representatives voted down the $700bn rescue plan (TARP); US shares had one of their worst days on record.", ("equities", "usd", "gold")),
    ("2008-10-08", "Central banks cut rates together", "The Fed, the European Central Bank, the Bank of England and others cut interest rates at the same time in a coordinated move.", ("all",)),
    ("2008-11-25", "Fed starts buying mortgage bonds (QE1)", "The Federal Reserve announced it would buy hundreds of billions of dollars of mortgage-related debt: the start of quantitative easing.", ("equities", "usd", "gold")),
    ("2008-12-16", "Fed cuts rates to near zero", "The Federal Reserve cut its interest rate to a range of 0 to 0.25%, the lowest ever.", ("usd", "equities", "gold")),
    ("2009-03-05", "Bank of England cuts to 0.5% and starts QE", "The Bank of England cut Bank Rate to 0.5%, its lowest ever, and announced £75bn of quantitative easing.", ("gbp", "uk_equities")),
    ("2009-03-18", "Fed expands QE to government bonds", "The Federal Reserve said it would buy US government bonds as well as more mortgage debt; the dollar fell sharply.", ("usd", "gold", "equities")),
    ("2010-05-03", "Greece's first bailout agreed", "Over the weekend euro-area countries and the IMF agreed a €110bn rescue loan for Greece.", ("eur", "eu_equities")),
    ("2010-05-06", "The 'flash crash'", "US shares plunged and recovered within minutes in the afternoon; the Dow Jones fell nearly 1,000 points at its low.", ("us_equities",)),
    ("2010-05-10", "€750bn euro rescue fund", "Over the weekend the EU and IMF agreed a rescue package of up to €750bn to support euro-area countries.", ("eur", "eu_equities", "equities")),
    ("2010-08-05", "Russia bans grain exports", "After drought and wildfires, Russia announced a ban on grain exports; wheat prices jumped.", ("grains",)),
    ("2010-11-03", "Fed announces QE2", "The Federal Reserve announced a further $600bn of government bond purchases.", ("usd", "gold", "equities")),
    ("2011-03-11", "Earthquake and tsunami in Japan", "A huge earthquake and tsunami struck north-east Japan, damaging the Fukushima nuclear plant.", ("japan", "jpy", "equities")),
    ("2011-03-18", "G7 steps in to weaken the yen", "After the yen surged to a record against the dollar, the G7 countries intervened together in currency markets.", ("jpy",)),
    ("2011-08-08", "US loses its AAA credit rating", "On Friday after the close, S&P cut the US government's credit rating from AAA to AA+; this was the first trading day after.", ("equities", "usd", "gold")),
    ("2011-09-06", "Swiss franc capped", "The Swiss National Bank set a minimum exchange rate of 1.20 francs per euro to stop the franc rising.", ("chf", "eur")),
    ("2012-07-26", "Draghi: 'whatever it takes'", "ECB President Mario Draghi said the ECB was ready to do 'whatever it takes' to preserve the euro.", ("eur", "eu_equities", "equities")),
    ("2012-09-13", "Fed announces open-ended QE3", "The Federal Reserve said it would buy $40bn of mortgage debt a month with no fixed end date.", ("usd", "gold", "equities")),
    ("2012-12-17", "Abe wins Japan's election", "Shinzo Abe's party won Japan's general election on the Sunday, on a promise of aggressive monetary easing.", ("jpy", "japan")),
    ("2013-03-18", "Cyprus bailout hits bank deposits", "Over the weekend a Cyprus rescue deal included a levy on bank deposits, unsettling euro markets.", ("eur", "eu_equities")),
    ("2013-04-04", "Bank of Japan's huge easing", "The Bank of Japan announced it would double the money supply within two years.", ("jpy", "japan")),
    ("2013-04-15", "Gold's sharp sell-off", "Gold fell by around 9% in one of its biggest one-day drops, following a large fall the Friday before.", ("gold", "silver", "metals")),
    ("2013-05-22", "Bernanke hints at slowing QE", "Fed Chair Ben Bernanke told Congress the Fed could slow its bond buying, setting off the 'taper tantrum' in bond markets.", ("usd", "equities", "gold")),
    ("2013-12-18", "Fed begins to taper QE", "The Federal Reserve announced it would reduce its monthly bond purchases by $10bn.", ("usd", "equities", "gold")),
    ("2014-10-31", "Bank of Japan surprises with more easing", "The Bank of Japan unexpectedly expanded its asset purchases.", ("jpy", "japan")),
    ("2014-11-27", "OPEC decides not to cut output", "OPEC kept its production target unchanged despite falling prices; oil dropped sharply.", ("oil", "energy")),
    ("2015-01-15", "Swiss franc cap scrapped", "The Swiss National Bank suddenly abandoned its 1.20 minimum against the euro; the franc jumped by well over 10% against the euro within minutes.", ("chf", "eur")),
    ("2015-01-22", "ECB launches QE", "The European Central Bank announced it would buy €60bn of bonds a month.", ("eur", "eu_equities")),
    ("2015-07-06", "Greece votes No", "In a Sunday referendum, Greek voters rejected the bailout terms offered by creditors.", ("eur", "eu_equities")),
    ("2015-08-11", "China devalues the yuan", "China's central bank devalued the yuan by nearly 2%, its biggest move in decades.", ("cny", "equities", "metals", "aud")),
    ("2015-08-24", "Global sell-off led by China", "Chinese shares fell over 8% and global markets slid; the Dow Jones dropped about 1,000 points shortly after the open.", ("equities", "oil", "aud")),
    ("2015-12-16", "Fed raises rates for the first time in nearly a decade", "The Federal Reserve raised its interest rate from near zero to 0.25–0.5%.", ("usd", "gold")),
    ("2016-01-29", "Bank of Japan adopts negative rates", "The Bank of Japan unexpectedly introduced a negative interest rate of -0.1%.", ("jpy", "japan")),
    ("2016-06-24", "UK votes to leave the EU", "Results of the 23 June referendum showed a vote to leave the EU; the pound fell to its lowest since 1985.", ("gbp", "uk_equities", "equities", "gold", "eur")),
    ("2016-08-04", "Bank of England cuts to 0.25%", "The Bank of England cut Bank Rate to 0.25% and restarted quantitative easing after the referendum.", ("gbp", "uk_equities")),
    ("2016-10-07", "Pound 'flash crash'", "Sterling briefly fell about 6% against the dollar in thin Asian trading before partly recovering.", ("gbp",)),
    ("2016-11-09", "Trump wins the US election", "Results through the night showed Donald Trump winning the presidency; markets swung sharply overnight.", ("usd", "equities", "gold")),
    ("2016-11-30", "OPEC agrees its first output cut since 2008", "OPEC members agreed to reduce oil production.", ("oil", "energy")),
    ("2017-06-09", "UK election gives a hung parliament", "The Conservatives lost their majority in the 8 June general election; the pound fell.", ("gbp", "uk_equities")),
    ("2018-02-05", "Volatility shock hits US shares", "The Dow Jones fell nearly 1,200 points, then its biggest one-day points fall, as a spike in volatility hit markets.", ("us_equities", "equities")),
    ("2018-03-22", "US announces tariffs on Chinese goods", "President Trump announced tariffs on up to $60bn of Chinese imports.", ("equities", "cny", "grains")),
    ("2018-04-04", "China targets US soybeans", "China announced plans for 25% tariffs on US soybeans and other goods in response to US tariffs.", ("grains", "equities")),
    ("2019-07-31", "Fed cuts rates for the first time since 2008", "The Federal Reserve cut its interest rate by 0.25%.", ("usd", "gold", "equities")),
    ("2019-08-05", "Yuan weakens past 7 per dollar", "China let the yuan fall past 7 per dollar and the US labelled China a currency manipulator.", ("cny", "equities", "gold", "aud")),
    ("2019-09-16", "Attack on Saudi oil facilities", "Over the weekend, drone and missile attacks knocked out about half of Saudi Arabia's oil output; Brent jumped by a record amount.", ("oil", "energy")),
    ("2019-12-13", "Conservative majority in UK election", "Results of the 12 December election gave the Conservatives a large majority; the pound rose.", ("gbp", "uk_equities")),
    ("2020-01-03", "US strike kills Iranian general", "A US strike in Baghdad killed Iranian commander Qasem Soleimani; oil and gold rose.", ("oil", "gold")),
    ("2020-02-24", "Coronavirus spreads to Italy and South Korea", "Global shares fell sharply as outbreaks grew outside China.", ("equities", "oil")),
    ("2020-03-03", "Fed makes an emergency cut", "The Federal Reserve cut rates by 0.5% between meetings in response to the coronavirus.", ("usd", "equities")),
    ("2020-03-09", "Oil price war", "After OPEC+ talks collapsed, Saudi Arabia cut prices and planned to raise output; oil fell about 25% and US share trading was briefly halted.", ("oil", "energy", "equities")),
    ("2020-03-11", "WHO declares a pandemic", "The World Health Organization declared COVID-19 a pandemic; the Bank of England made an emergency cut to 0.25%.", ("all",)),
    ("2020-03-16", "Fed cuts to zero and restarts QE", "On the Sunday the Federal Reserve cut rates to near zero and announced $700bn of asset purchases.", ("all",)),
    ("2020-03-19", "Bank of England cuts to 0.1%", "The Bank of England cut Bank Rate to 0.1%, its lowest ever, and expanded QE.", ("gbp", "uk_equities")),
    ("2020-03-23", "Fed announces unlimited QE", "The Federal Reserve said it would buy assets 'in the amounts needed'.", ("all",)),
    ("2020-04-13", "Record OPEC+ output cut", "Over the weekend OPEC+ agreed to cut production by about 9.7m barrels a day.", ("oil", "energy")),
    ("2020-04-20", "US oil futures go negative", "The expiring US oil (WTI) futures contract settled below zero for the first time, as storage ran out.", ("oil", "energy")),
    ("2020-11-09", "First effective COVID vaccine announced", "Pfizer and BioNTech said their vaccine was over 90% effective in trials; shares and oil jumped.", ("equities", "oil", "gold")),
    ("2020-12-24", "UK and EU agree a trade deal", "The UK and EU agreed a post-Brexit trade agreement.", ("gbp", "uk_equities")),
    ("2021-03-23", "Ship blocks the Suez Canal", "The container ship Ever Given ran aground and blocked the Suez Canal, a key oil shipping route.", ("oil",)),
    ("2022-02-24", "Russia invades Ukraine", "Russia launched a full-scale invasion of Ukraine; oil, gas, wheat and gold surged and shares fell.", ("all",)),
    ("2022-03-08", "Commodity prices spike", "Oil reached its highest since 2008 and the London Metal Exchange suspended nickel trading after a price surge.", ("oil", "energy", "metals", "grains")),
    ("2022-03-16", "Fed starts raising rates", "The Federal Reserve raised rates for the first time since 2018 to fight inflation.", ("usd", "equities", "gold")),
    ("2022-06-15", "Fed raises rates by 0.75%", "The Federal Reserve made its biggest rate rise since 1994.", ("usd", "equities", "gold")),
    ("2022-09-22", "Japan intervenes to support the yen", "Japan bought yen in the currency market for the first time since 1998.", ("jpy",)),
    ("2022-09-23", "UK 'mini-budget'", "The UK government announced large unfunded tax cuts; the pound and UK government bonds fell sharply.", ("gbp", "uk_equities")),
    ("2022-09-26", "Pound hits a record low", "Sterling fell to a record low against the dollar in early Asian trading.", ("gbp",)),
    ("2022-09-28", "Bank of England steps into the bond market", "The Bank of England began emergency purchases of long-dated government bonds to calm markets.", ("gbp", "uk_equities")),
    ("2022-10-20", "Liz Truss resigns", "The UK Prime Minister resigned after 45 days in office.", ("gbp",)),
    ("2022-11-10", "US inflation lower than expected", "US consumer price inflation came in below forecasts; the Nasdaq rose over 7%.", ("usd", "equities", "gold")),
    ("2023-03-10", "Silicon Valley Bank collapses", "US regulators closed Silicon Valley Bank after a run on deposits.", ("equities", "usd", "gold")),
    ("2023-03-20", "UBS takes over Credit Suisse", "Over the weekend UBS agreed to buy Credit Suisse in a rescue arranged by the Swiss authorities.", ("equities", "chf", "eu_equities")),
    ("2023-07-17", "Russia quits the Black Sea grain deal", "Russia pulled out of the deal that let Ukraine ship grain through the Black Sea; wheat rose.", ("grains",)),
    ("2023-08-02", "Fitch downgrades the US", "Late on 1 August, Fitch cut the US government's credit rating from AAA to AA+.", ("usd", "equities")),
    ("2023-10-09", "Hamas attacks Israel", "After the 7 October attack and the war that began, oil and gold rose on the first trading day.", ("oil", "gold")),
    ("2024-03-19", "Bank of Japan ends negative rates", "The Bank of Japan raised rates for the first time in 17 years.", ("jpy", "japan")),
    ("2024-07-05", "Labour wins UK election", "Results of the 4 July general election gave Labour a large majority.", ("gbp", "uk_equities")),
    ("2024-08-05", "Global market rout", "Japan's Nikkei fell over 12%, its biggest points drop, as yen-funded trades unwound after weak US jobs data.", ("japan", "jpy", "equities")),
    ("2024-09-18", "Fed cuts by 0.5%", "The Federal Reserve made its first rate cut since 2020.", ("usd", "gold", "equities")),
    ("2024-11-06", "Trump wins the US election", "Results through the night showed Donald Trump winning a second term.", ("usd", "equities", "gold")),
    ("2025-01-27", "DeepSeek shakes US tech shares", "A low-cost Chinese AI model prompted a sell-off in US technology shares; Nvidia fell about 17%.", ("us_equities",)),
    ("2025-04-03", "US announces sweeping tariffs", "The evening before, the US announced tariffs on imports from almost every country; markets fell sharply.", ("all",)),
    ("2025-04-09", "US pauses most new tariffs", "The US paused most of the new tariffs for 90 days; the S&P 500 rose about 9.5%, one of its best days.", ("equities", "usd", "oil")),
]


def tags_for(symbol: Symbol) -> set[str]:
    """Which event tags apply to a market."""
    code, cls = symbol.code.upper(), symbol.asset_class
    tags = {"all"}
    if cls in ("stock", "etf"):
        tags |= {"equities", "us_equities"}
    elif cls == "ukstock":
        tags |= {"equities", "uk_equities"}
    elif cls == "index":
        tags.add("equities")
        if any(x in code for x in ("SPX", "NAS", "US30", "US2000")):
            tags.add("us_equities")
        if "UK100" in code:
            tags.add("uk_equities")
        if any(x in code for x in ("DE30", "DE40", "EU50", "FR40", "NL25", "ES35")):
            tags.add("eu_equities")
        if "JP225" in code:
            tags.add("japan")
    elif cls == "metal":
        tags.add("metals")
        if code.startswith("XAU"):
            tags.add("gold")
        if code.startswith("XAG"):
            tags.add("silver")
    elif cls == "commodity":
        if any(x in code for x in ("BCO", "WTICO")):
            tags |= {"oil", "energy"}
        elif "NATGAS" in code:
            tags |= {"gas", "energy"}
        elif any(x in code for x in ("CORN", "WHEAT", "SOYBN", "SUGAR")):
            tags.add("grains")
        elif "XCU" in code:
            tags.add("metals")
    elif cls == "forex":
        for ccy in ("USD", "GBP", "EUR", "JPY", "CHF", "AUD", "CNH", "CNY"):
            if ccy in code:
                tags.add("cny" if ccy in ("CNH", "CNY") else ccy.lower())
    elif cls == "bond":
        if "USB" in code:
            tags.add("usd")
        if "UK" in code:
            tags.add("gbp")
        if "DE" in code:
            tags.add("eur")
    return tags


def for_market(symbol: Symbol, start_ts: int, end_ts: int) -> list[dict]:
    """Events that touched this market between two times (Unix seconds), oldest first."""
    mine = tags_for(symbol)
    out = []
    for day, title, text, tags in EVENTS:
        ts = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        if start_ts <= ts <= end_ts and mine & set(tags):
            out.append({"date": day, "time": ts, "title": title, "text": text})
    return out
