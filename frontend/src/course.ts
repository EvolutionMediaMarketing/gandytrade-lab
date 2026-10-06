/**
 * The 12-week course: short lessons, a quiz and one task in the app per week.
 *
 * Written for a beginner with a small account who wants to learn steadily without it taking over their life.
 * The facts here are general education, not advice; anything about tax or regulation says to check current rules.
 * Week numbers and task keys must match `backend/app/course.py`, which tracks progress and checks the tasks.
 */

export interface Lesson {
  title: string;
  body: string[]; // paragraphs
}

export interface QuizQuestion {
  q: string;
  options: string[];
  answer: number; // index into options
  why: string;
}

export interface CourseTask {
  /** "auto": the app checks it from what you've done. "self": you tick it. "plan": you write it here. */
  kind: "auto" | "self" | "plan";
  text: string;
  /** Where to do it. */
  go?: { page: "charts" | "backtest" | "paper" | "journal" | "review" | "tools"; label: string };
}

export interface Week {
  week: number;
  title: string;
  goal: string;
  lessons: Lesson[];
  quiz: QuizQuestion[];
  task: CourseTask;
}

export const PASS_MARK = 3; // of 4

export const COURSE: Week[] = [
  {
    week: 1,
    title: "Start here",
    goal: "Know what trading really involves, read a price chart, and place your first paper trade.",
    lessons: [
      {
        title: "What you're actually doing",
        body: [
          "A trade is a bet that a price will move one way before it moves the other. When you buy, someone sells to you, and they think the opposite. Nobody knows what happens next; the aim is to be right a little more often, or win a little more when right, than you lose when wrong.",
          "Most people who trade short-term lose money, especially with leverage. UK brokers must publish the share of their customers' CFD accounts that lose money, and it's usually well over half. That's not a reason to give up, but it is why this lab starts with pretend money, small risks and fixed rules.",
          "The realistic goal for the first year is not to get rich. It's to learn a repeatable process, find out how you behave when trades go against you, and keep your account intact while you do.",
        ],
      },
      {
        title: "Reading a candle",
        body: [
          "Each candle on a chart shows one slice of time: a minute, an hour, a day. Its body runs from the price at the start (the open) to the price at the end (the close). The thin lines above and below, the wicks, show the highest and lowest prices in that time.",
          "Green (or hollow) candles closed higher than they opened; red ones closed lower. A long body means a strong move; long wicks mean the price went somewhere and came back.",
          "The timeframe changes the story. A daily chart might show a steady rise while the 5-minute chart shows chaos. Start with daily candles: they move slowly enough to think, and they suit someone checking in once a day.",
        ],
      },
      {
        title: "Buying, selling short and the spread",
        body: [
          "Buying (going long) makes money if the price rises. Selling short makes money if it falls. With real shares you can only buy; CFDs and spread bets let you go short too.",
          "There are always two prices: a higher one to buy at and a lower one to sell at. The gap is the spread, and it's how most brokers are paid. You start every trade slightly behind, by half the spread each way, so a trade has to move in your favour just to break even.",
          "The app includes the spread, slippage and other costs in every paper trade and backtest, so the results are what you'd really have got.",
        ],
      },
    ],
    quiz: [
      { q: "You buy a market. What has to happen for you to make money?", options: ["The price rises enough to cover the spread, then some", "The price stays the same", "The price falls", "Nothing: buying is free"], answer: 0, why: "You buy at the higher price and sell at the lower one, so the price must rise past the spread before you're in profit." },
      { q: "A daily candle has a small body near the top and a long wick below it. What happened that day?", options: ["The price fell a long way, then recovered most of it by the close", "The price rose steadily all day", "Nothing much: it was a quiet day", "The market was closed"], answer: 0, why: "The long lower wick shows the day's low was far below the close: sellers pushed it down, and buyers brought it back." },
      { q: "Which can you do with real shares?", options: ["Only buy", "Buy or sell short", "Only sell short", "Use 30:1 leverage"], answer: 0, why: "Real shares are owned outright: you can buy and later sell them, but not bet on a fall or borrow to trade bigger." },
      { q: "What's the sensible goal for your first year?", options: ["Learn a repeatable process and keep the account intact", "Double the account", "Trade as often as possible to learn faster", "Find one market that always goes up"], answer: 0, why: "Skill comes from a process you can repeat and review. Big targets push beginners into big risks." },
    ],
    task: { kind: "auto", text: "Place your first paper trade, completing the pre-trade checklist.", go: { page: "charts", label: "Open Charts → Plan a trade" } },
  },
  {
    week: 2,
    title: "Risk comes first",
    goal: "Understand why small losses matter and how the 1% rule sizes every trade.",
    lessons: [
      {
        title: "Why small losses matter",
        body: [
          "Losses and gains aren't symmetrical. Lose 10% and you need 11% to get back. Lose 20% and you need 25%. Lose 50% and you need 100%: you'd have to double what's left just to break even.",
          "That's why professional traders obsess over the downside first. A strategy that makes a bit less but never falls far is worth more than one that makes more but sometimes halves the account, because you can actually stick with it.",
        ],
      },
      {
        title: "The 1% rule",
        body: [
          "Before each trade, decide the most you'll lose if it goes wrong, and keep that to 1% of the account. On £200, that's £2.",
          "It sounds tiny. But even good strategies have runs of 10 or more losses in a row. At 1% a trade, ten straight losses cost about 9.6% of the account: painful but survivable. At 5% a trade, the same run costs about 40%, and few people keep going after that.",
          "Your paper accounts use 1% by default, with a cap of 2%. The backtests showed why: 2% risk doubled the worst fall to about 40%.",
        ],
      },
      {
        title: "Position size follows the stop",
        body: [
          "The amount you buy isn't a feeling; it's arithmetic. Units = the £ you're willing to lose ÷ the distance from your entry to your stop-loss (converted to pounds).",
          "So a wide stop means a small position, and a tight stop means a bigger one. The £ at risk stays the same either way. The trade planner does this sum for you every time you drag a line.",
        ],
      },
    ],
    quiz: [
      { q: "Your account falls 50%. What gain gets you back to where you started?", options: ["100%", "50%", "75%", "25%"], answer: 0, why: "Half the account has to double to return to the start." },
      { q: "With £200 and 1% risk, how much do you lose if the stop-loss is hit?", options: ["About £2", "About £20", "About £1", "It depends how far away the stop is"], answer: 0, why: "1% of £200 is £2. The stop's distance changes the size of the position, not the £ at risk." },
      { q: "You move your stop-loss twice as far from the entry. What should happen to the position size?", options: ["It halves", "It doubles", "It stays the same", "It doesn't matter"], answer: 0, why: "Twice the distance means each unit can lose twice as much, so you hold half as many to keep the same £ risk." },
      { q: "Why risk only 1% a trade?", options: ["So a normal losing run doesn't do lasting damage", "Because big trades are illegal", "Because 1% guarantees a profit", "Because brokers require it"], answer: 0, why: "Losing runs are normal. Small risk means you're still standing, and still thinking clearly, when the winners come." },
    ],
    task: { kind: "self", text: "In Plan a trade, set up trades on three different markets with the same risk, and notice how the size changes with the stop distance.", go: { page: "charts", label: "Open Charts → Plan a trade" } },
  },
  {
    week: 3,
    title: "Stops and targets",
    goal: "Place stops beyond normal noise, think in R, and know when trailing stops and price orders help.",
    lessons: [
      {
        title: "Where a stop-loss goes",
        body: [
          "A stop-loss should sit where the trade idea is clearly wrong, not where the loss feels uncomfortable. Put it too close and ordinary wobbles stop you out of trades that would have worked.",
          "ATR (average true range) measures how far a market typically moves in a day. A stop 1.5 to 3 times the ATR away is a sensible starting range; the planner suggests 2 ×. The planner shows your stop distance as a multiple of the daily move, and warns if it's under 1 ×.",
          "One firm rule: never move a stop further away once a trade is open. The app allows it but marks it in your rule score, because it's how small losses become big ones.",
        ],
      },
      {
        title: "Thinking in R",
        body: [
          "R is what you risked on a trade. Lose at the stop and that's -1R. Win twice what you risked and that's +2R. Measuring in R lets you compare trades of any size on any market.",
          "Your target sets the win rate you need. With a 2R target, you break even (before costs) if a third of trades win. With a 1R target, you need half. With 3R, a quarter. The 'How realistic is this target?' box shows how often targets like yours were actually reached in the past.",
        ],
      },
      {
        title: "Trailing stops and price orders",
        body: [
          "A trailing stop follows the price as it moves your way and never moves back, locking in some profit. The catch: in a long trend, a tight trail often stops you out on a normal pullback, just before the trend continues. Trail at 2 to 3 × the daily move, not closer.",
          "A price order waits for a level. A buy stop sits above the price and buys a breakout; a buy limit sits below and buys a dip. Choosing 'When the market opens' queues a trade for the opening price, which can jump from the last close.",
        ],
      },
    ],
    quiz: [
      { q: "Where should a stop-loss go?", options: ["Where the trade idea is clearly wrong, beyond normal noise", "As close as possible to keep losses small", "Wherever the loss feels comfortable", "There's no need for one on paper"], answer: 0, why: "A stop inside the normal day-to-day range gets hit by noise. It belongs where the reason for the trade has failed." },
      { q: "You risk £2 and win £6. What's that in R?", options: ["+3R", "+6R", "+2R", "+1R"], answer: 0, why: "£6 ÷ £2 risked = 3R." },
      { q: "With a 2R target and no costs, what share of trades must win to break even?", options: ["About a third", "Half", "Two-thirds", "A tenth"], answer: 0, why: "One 2R win pays for two 1R losses, so winning one trade in three breaks even." },
      { q: "The price is 100. You want to buy only if it breaks above 105. Which order?", options: ["Buy stop at 105", "Buy limit at 105", "Sell stop at 105", "Buy now"], answer: 0, why: "A buy stop sits above the price and fills when the price rises to it: buying the breakout." },
    ],
    task: { kind: "self", text: "On two markets, use 'How realistic is this target?' in Plan a trade to compare a 1R and a 3R target: how often each was reached, and which paid its way after costs.", go: { page: "charts", label: "Open Charts → Plan a trade" } },
  },
  {
    week: 4,
    title: "Your journal",
    goal: "Use the journal and rule score to learn from every trade, win or lose.",
    lessons: [
      {
        title: "Why keep a journal",
        body: [
          "Memory flatters us. We remember the brilliant trade and forget the three we rushed. A journal written at the time is the only honest record of what you were thinking.",
          "Judge each trade on the process, not the result. A trade that followed every rule and lost was a good trade. One that broke the rules and won was a bad trade that got lucky, and luck teaches the wrong lesson.",
        ],
      },
      {
        title: "The rule score",
        body: [
          "Every trade you place yourself starts at 100 and loses points for each rule broken. The app marks three: trading against the trend you said you saw, opening a trade within 30 minutes of a loss (revenge trading), and moving a stop-loss further away.",
          "A falling rule score is an early warning. Results swing with luck for months; your rule score shows straight away whether you're trading the way you planned.",
        ],
      },
      {
        title: "Moods and patterns",
        body: [
          "The checklist asks how you're feeling. It seems soft, but it's data. After 20 or 30 trades, filter the Journal page by mood: many people find their 'fear of missing out' and 'frustrated' trades lose far more than their 'calm' ones.",
          "Write one line, the lesson, for every closed trade. Keep it specific: 'waited for the daily close before entering' beats 'be patient'.",
        ],
      },
    ],
    quiz: [
      { q: "A trade followed all your rules and hit its stop-loss. What was it?", options: ["A good trade with a bad outcome", "A bad trade", "A mistake to avoid", "Proof the strategy doesn't work"], answer: 0, why: "Losses are part of any strategy. Following the plan is the part you control." },
      { q: "Which of these lowers your rule score?", options: ["Opening a trade 10 minutes after a loss", "Taking a loss at the stop", "Using a 2R target", "Trading a new market"], answer: 0, why: "A trade within 30 minutes of a loss is marked as possible revenge trading." },
      { q: "Why record your mood?", options: ["Over many trades it shows which states of mind cost you money", "The broker needs it", "It changes the position size", "It isn't useful"], answer: 0, why: "Patterns appear over 20–30 trades: filter the journal by mood to see them." },
      { q: "Which is the more useful lesson?", options: ["\"Entered before the daily candle closed; wait for the close next time\"", "\"Be more patient\"", "\"Markets are random\"", "\"Bad luck\""], answer: 0, why: "A specific, checkable action is a lesson you can actually apply next time." },
    ],
    task: { kind: "auto", text: "Write a lesson in the journal of three closed trades (yours, not automatic ones).", go: { page: "journal", label: "Open the Journal" } },
  },
  {
    week: 5,
    title: "Trends and indicators",
    goal: "Tell a trend from a range, and know what moving averages, RSI, ATR and the Ichimoku Cloud do and don't tell you.",
    lessons: [
      {
        title: "Trend or range?",
        body: [
          "An uptrend makes higher highs and higher lows; a downtrend, lower highs and lower lows. A range bounces between roughly the same high and low. Most strategies work in one and fail in the other, so this is the first question to ask of any chart.",
          "Zoom out before you zoom in. Check the weekly chart, then the daily. A daily dip inside a weekly uptrend is a very different thing from a daily dip in a weekly downtrend.",
        ],
      },
      {
        title: "Moving averages, RSI and ATR",
        body: [
          "A moving average is the average closing price of the last N candles. Price above a rising 200-day average is a common definition of a long-term uptrend.",
          "RSI (0 to 100) compares recent gains with recent losses. Below 30 is called oversold and above 70 overbought, but in a strong trend RSI can stay 'overbought' for weeks while the price keeps rising.",
          "ATR doesn't show direction at all, just how much the market typically moves. It's for sizing stops, not for picking trades.",
          "Every indicator is calculated from past prices, so they all lag. They describe; they don't predict.",
        ],
      },
      {
        title: "The Ichimoku Cloud",
        body: [
          "Ichimoku packs several lines into one view. The cloud is the shaded area; price above it suggests an uptrend, below it a downtrend, and inside it, no clear trend. The cloud's thickness hints at how much support or resistance sits there.",
          "Its fast and slow lines (Tenkan and Kijun) cross like moving averages, and the lagging line compares today's price with the price 26 candles ago. It's a good trend filter, but like everything else it's built from the past.",
        ],
      },
    ],
    quiz: [
      { q: "Higher highs and higher lows describe…", options: ["An uptrend", "A downtrend", "A range", "High volatility"], answer: 0, why: "Each swing goes further up and doesn't fall back as far: an uptrend." },
      { q: "RSI has been above 70 for two weeks while the price keeps rising. What does that tell you?", options: ["The trend is strong; 'overbought' isn't a sell signal on its own", "A fall is certain", "The indicator is broken", "Buy more immediately"], answer: 0, why: "In strong trends RSI can stay high for a long time. Overbought describes; it doesn't forecast." },
      { q: "What does ATR measure?", options: ["How much the market typically moves", "Which way the trend is going", "Whether to buy", "The spread"], answer: 0, why: "ATR measures the size of typical moves, not their direction." },
      { q: "On Ichimoku, the price is inside the cloud. What does that suggest?", options: ["No clear trend", "A strong uptrend", "A strong downtrend", "The market is closed"], answer: 0, why: "Above the cloud suggests up, below suggests down, inside suggests undecided." },
    ],
    task: { kind: "self", text: "Add the Ichimoku Cloud to the daily chart of three markets. Decide whether each is trending up, down or ranging, then check the weekly chart: did it agree?", go: { page: "charts", label: "Open Charts" } },
  },
  {
    week: 6,
    title: "Strategies are fixed rules",
    goal: "See why fixed rules beat judgement for a beginner, and how trend-following and reversal strategies differ.",
    lessons: [
      {
        title: "Why rules beat gut feel",
        body: [
          "A strategy is a set of rules precise enough that two people would take the same trades: when to enter, where the stop goes, when to exit. Rules can be tested on the past; gut feel can't.",
          "Rules also protect you from yourself. When a trade is losing, every instinct says do something. A rule decided in advance, with a clear head, is usually better than a decision made under stress.",
        ],
      },
      {
        title: "Trend-following versus reversal",
        body: [
          "Trend-followers, like the Breakout strategy, buy strength and ride it. They lose small and often, then catch a few big moves that pay for everything. Expect win rates around 35–45% and long flat or slightly losing spells.",
          "Reversal (mean-reversion) strategies, like the RSI reversal or Bollinger bounce, buy weakness expecting a bounce. They win often but small, and occasionally take a large loss when the 'bounce' becomes a crash.",
          "Neither is better. They suit different markets and different temperaments. Many people find the long losing runs of trend-following harder to live with than they expect.",
        ],
      },
      {
        title: "Reading a strategy card",
        body: [
          "On the Learn page, each strategy shows its rules, when it tends to work and fail, and its settings. Read the 'tends to fail' line first: it tells you what kind of market will hurt.",
          "Breakout 55/20 means: buy on a close above the highest high of the last 55 candles, sell on a close below the lowest low of the last 20. Slower settings trade less and pay less in costs.",
        ],
      },
    ],
    quiz: [
      { q: "What makes something a strategy rather than an opinion?", options: ["Rules precise enough to test on past prices", "A strong feeling about the market", "A tip from a forum", "Lots of indicators on the chart"], answer: 0, why: "If two people would take the same trades from the rules, it can be tested. Opinions can't." },
      { q: "Which is typical of trend-following?", options: ["Many small losses, a few big wins", "Many small wins, a few big losses", "Winning almost every trade", "No losing runs"], answer: 0, why: "Trend-followers cut losers quickly and let a few big trends pay for them." },
      { q: "What's the main danger of a reversal strategy?", options: ["The occasional large loss when a dip keeps falling", "It never wins", "It trades too rarely", "It can't use stop-losses"], answer: 0, why: "Buying weakness works until the weakness turns into a real trend down." },
      { q: "Breakout 55/20 buys when…", options: ["The price closes above the highest high of the last 55 candles", "The price falls for 55 days", "The 20-day average crosses the 55-day", "RSI is below 20"], answer: 0, why: "55 is the breakout length (entry); 20 is the exit length." },
    ],
    task: { kind: "auto", text: "Backtest any strategy on one market (Backtest page, One market).", go: { page: "backtest", label: "Open Backtest" } },
  },
  {
    week: 7,
    title: "Backtesting honestly",
    goal: "Read a backtest critically: costs, buy and hold, sample size and the overfitting trap.",
    lessons: [
      {
        title: "Costs are real",
        body: [
          "Every trade pays the spread, possibly slippage, and with CFDs, overnight financing. Strategies that trade often feel these costs most. Your own test showed it: the 20/10 breakout on daily candles paid 88% of its gross profit in costs.",
          "A backtest without costs is fiction. Every result in this app includes them; check the 'Costs paid' figure next to the profit.",
        ],
      },
      {
        title: "Beat buy and hold, or why bother?",
        body: [
          "Every backtest compares the strategy with simply buying and holding the same market. If a strategy can't beat that after costs, the work of trading it isn't paying.",
          "Return isn't everything, though. Your basket tests made less than holding, but with much smaller falls (about 28% against 39–50%). Whether that trade-off is worth it is a personal judgement about how much pain you can stand.",
        ],
      },
      {
        title: "Enough trades, and the overfitting trap",
        body: [
          "Under 30 trades, a result can easily be luck. The app warns you, and you should take that seriously.",
          "The bigger trap: try enough settings and one will look brilliant by chance. That's overfitting, and it's the commonest way backtests lie. Decide on one or two settings before you test, and treat a result that only works with one exact number as a warning sign.",
        ],
      },
    ],
    quiz: [
      { q: "A strategy made 30% before costs and 4% after. What does that suggest?", options: ["It trades too often for its edge", "It's excellent", "Costs don't matter", "The backtest is broken"], answer: 0, why: "Most of the gross profit went on costs: the edge per trade is too small for how often it trades." },
      { q: "Why compare with buy and hold?", options: ["If a strategy can't beat simply holding after costs, the effort isn't paying", "Buy and hold is always worse", "It's required by law", "It sets the stop-loss"], answer: 0, why: "Holding costs almost nothing in time or trading costs. A strategy has to earn its keep against it." },
      { q: "A backtest shows 12 trades and +60%. How much should you trust it?", options: ["Very little: too few trades to tell skill from luck", "Completely", "It proves the strategy works", "More than one with 200 trades"], answer: 0, why: "With so few trades, one or two lucky winners can explain the whole result." },
      { q: "You try 40 setting combinations and pick the best. What's the risk?", options: ["You've likely found luck that won't repeat (overfitting)", "None: more tests are always better", "The costs will be too low", "The strategy will trade too rarely"], answer: 0, why: "The best of 40 tries is partly the luckiest. The walk-forward check exists to catch this." },
    ],
    task: { kind: "self", text: "Backtest one strategy with its standard settings on three markets. Note which beat buy and hold after costs, and how many trades each had.", go: { page: "backtest", label: "Open Backtest" } },
  },
  {
    week: 8,
    title: "Is it skill or luck?",
    goal: "Use the Monte Carlo and walk-forward checks, and read the robustness verdict.",
    lessons: [
      {
        title: "Monte Carlo: what luck alone could do",
        body: [
          "A backtest is one history: the trades in one particular order. The Monte Carlo check reshuffles those trades 2,000 times to show the range of outcomes and falls that the same strategy could have produced with different luck.",
          "Plan for the '1 in 20' worst fall, not the backtest's own. If the 1-in-20 fall is 30%, you need to be able to sit through 30% without abandoning the plan.",
        ],
      },
      {
        title: "Walk-forward: testing on unseen years",
        body: [
          "Settings chosen by looking at the whole history are flattered by hindsight. The walk-forward check tunes the settings on three stretches of history, then trades them on the next stretch they've never seen, six times over.",
          "The key number is 'edge kept': how much of the tuned return survived on unseen years. 50% or more is a good sign. Well below means the tuning mostly found luck.",
        ],
      },
      {
        title: "The four verdicts",
        body: [
          "Reject: it failed on unseen years; change the idea, not just the numbers. Watchlist: something's there, but with a real weakness. Incubate: it held up with a doubt or two; worth paper trading. Candidate: it passed every check; paper trade it, then judge it against the graduation bar.",
          "Your 55/20 basket came out as Watchlist: the edge survived, but only 2 of 6 unseen stretches made money, as trend-followers' long flat spells would predict.",
        ],
      },
    ],
    quiz: [
      { q: "The Monte Carlo 1-in-20 worst fall is 30%; the backtest's own was 22%. Which do you plan for?", options: ["30%", "22%", "The average of the two", "Neither"], answer: 0, why: "The backtest's history was just one ordering. Plan for a bad but plausible one." },
      { q: "What does the walk-forward check protect against?", options: ["Settings that only looked good because they were chosen with hindsight", "High costs", "Market closures", "Wrong stop-loss sizes"], answer: 0, why: "It always tests settings on years they weren't chosen on." },
      { q: "'Edge kept' is 20%. What does that suggest?", options: ["Most of the tuned result was luck", "An excellent strategy", "The costs are too high", "Not enough trades"], answer: 0, why: "Only a fifth of the tuned return survived on unseen years." },
      { q: "A strategy is labelled Incubate. What next?", options: ["Run it on paper to see whether it behaves as tested", "Trade it with real money", "Delete it", "Raise the risk to 5%"], answer: 0, why: "Incubate means promising with doubts: paper trading is where those doubts get tested." },
    ],
    task: { kind: "self", text: "Run the walk-forward check on a backtest of your choice. Write down the verdict and which check, if any, failed.", go: { page: "backtest", label: "Open Backtest" } },
  },
  {
    week: 9,
    title: "Baskets and automatic runs",
    goal: "Spread a strategy across markets, respect the open-risk limit, and let fixed rules trade on paper.",
    lessons: [
      {
        title: "Why trade a basket",
        body: [
          "A trend-following rule on one market may trade only a few times a year. Across six or twelve markets, it gets many more chances, and a trend in gold can pay for a flat year in indices.",
          "Markets that move together don't diversify much. Gold and silver often trend together, as do US and Japanese share indices. A good basket mixes metals, energy, farm goods, indices and currencies.",
        ],
      },
      {
        title: "The open-risk limit",
        body: [
          "Each trade risks 1%, but what if eight trades are open at once and they all fall together? The open-risk limit caps the total at risk across open trades: 10% by default. When it's full, new trades are trimmed or skipped.",
          "In a basket that's not a theoretical worry: in sharp sell-offs, many markets fall at once. The limit is what keeps a bad week from becoming a disaster.",
        ],
      },
      {
        title: "Letting the rules run",
        body: [
          "An automatic paper run trades a strategy's rules exactly, with no AI and no second-guessing, through the same safeguards as your own trades. It removes the hardest part for many people: pulling the trigger after a run of losses.",
          "Your job becomes checking that it's behaving as the backtest said it would: similar win rate, similar average R, similar losing runs. The dashboard compares them for you.",
        ],
      },
    ],
    quiz: [
      { q: "Why might gold and silver together be less diversified than gold and wheat?", options: ["Gold and silver often move together", "Silver is cheaper", "Wheat doesn't trend", "They're traded in different currencies"], answer: 0, why: "Markets that move together tend to win and lose at the same time." },
      { q: "Nine trades risking 1% each are open, and two more markets signal. What does the 10% open-risk limit do?", options: ["Lets one more in and trims or skips the other", "Lets both in", "Closes the oldest trade", "Raises the limit for the day"], answer: 0, why: "Nine plus one is 10%: the limit. The eleventh trade would go over it, so it's made smaller or skipped." },
      { q: "What does an automatic paper run decide with AI?", options: ["Nothing: it follows the strategy's fixed rules", "When to enter", "When to exit", "The position size"], answer: 0, why: "Automatic runs only follow fixed rules; there's no AI in opening or closing trades." },
      { q: "An automatic run has had 20 trades. What should you check?", options: ["Whether its win rate and average R resemble the backtest", "Whether to double the risk", "Whether to change the settings each week", "Nothing until it's made money"], answer: 0, why: "The question is whether it behaves as tested, not whether it's lucky yet." },
    ],
    task: { kind: "auto", text: "Start an automatic paper run (or a basket of them) from a backtest result or the Paper page.", go: { page: "paper", label: "Open Paper" } },
  },
  {
    week: 10,
    title: "Losing runs and drawdowns",
    goal: "Expect losing runs, respect the drawdown pause, and know the mistakes stress causes.",
    lessons: [
      {
        title: "Losing runs are normal",
        body: [
          "With a 37% win rate, the chance that any given ten trades are all losers is about 1 in 100. Over a few hundred trades, a run of ten or more is likely. Your 55/20 Monte Carlo check said 10 in a row is typical and 15 happens in 1 history in 20.",
          "Write your expected worst run down before it happens. When it comes, you'll recognise it as the plan working normally rather than the strategy breaking.",
        ],
      },
      {
        title: "The drawdown pause",
        body: [
          "Paper accounts pause themselves after a 20% fall from their high point. That isn't a verdict that the strategy has failed; it's a forced moment to review.",
          "At the pause, ask: were the trades taken as the rules said? Is the fall within what the backtest and Monte Carlo predicted? If yes, resume. If not, find out what changed before trading on.",
        ],
      },
      {
        title: "Your head is the weak link",
        body: [
          "The common ways people turn a normal drawdown into a disaster: revenge trading to win it back, moving stops further away, raising the risk 'just this once', and abandoning the system at the bottom, right before the trend that would have paid.",
          "The weekly review exists for this. Ten minutes on a Sunday, looking at what you did rather than what the market did, catches these habits early.",
        ],
      },
    ],
    quiz: [
      { q: "Your strategy wins 37% of trades and has lost 9 in a row. What's most likely?", options: ["A normal losing run", "The strategy has stopped working", "The broker is cheating", "You should double the risk to recover"], answer: 0, why: "Runs like this are expected at that win rate. Check the trades followed the rules, then carry on." },
      { q: "An account pauses at a 20% fall. What first?", options: ["Review whether the trades followed the rules and the fall is within what was expected", "Resume immediately", "Switch to another strategy", "Raise the risk to recover faster"], answer: 0, why: "The pause is a forced review, not a verdict." },
      { q: "Which is a classic stress mistake?", options: ["Moving the stop further away so the trade 'has room'", "Taking the planned stop-loss", "Writing a journal entry", "Doing the weekly review"], answer: 0, why: "Widening stops turns small, planned losses into large, unplanned ones." },
      { q: "What does the weekly review focus on?", options: ["What you did, and whether it followed the plan", "Predicting next week's prices", "Finding new strategies", "How much you made"], answer: 0, why: "Your behaviour is the part you control and can improve." },
    ],
    task: { kind: "auto", text: "Complete a weekly review.", go: { page: "review", label: "Open Review" } },
  },
  {
    week: 11,
    title: "Leverage, accounts and costs (UK)",
    goal: "Understand leverage, the account types available in the UK, and the costs that quietly add up.",
    lessons: [
      {
        title: "Leverage cuts both ways",
        body: [
          "Leverage lets a small deposit (margin) control a much bigger position. At 30:1, £100 controls £3,000, so a 1% move against you costs £30, or 30% of that deposit.",
          "It doesn't change the 1% rule: the position size still comes from your stop and your risk. What leverage changes is how big a position you're allowed to take, and how fast a mistake can hurt. The roadmap's plan for real money starts with real shares and no leverage.",
        ],
      },
      {
        title: "Shares, CFDs and spread bets",
        body: [
          "Real shares: you own them, can't lose more than you put in, and UK shares carry 0.5% stamp duty when bought. Inside a Stocks and Shares ISA, gains are free of UK tax.",
          "CFDs and spread bets: contracts on a price, with leverage, shorting and overnight financing. In the UK, spread-betting profits have generally been free of capital gains tax, while CFD profits are taxable, though losses can be offset. Most retail accounts on these products lose money.",
          "Tax rules change and depend on your situation, so check HMRC's current guidance or ask a qualified adviser before relying on any of this.",
        ],
      },
      {
        title: "The costs that add up",
        body: [
          "Beyond the spread: overnight financing on leveraged positions (a few percent a year, charged daily), currency conversion fees when a market is priced in dollars, and commission on some share accounts.",
          "For a slow strategy holding trades for weeks, financing can matter more than the spread. The backtester includes it, so compare a strategy's result as real shares and as CFDs to see the difference.",
        ],
      },
    ],
    quiz: [
      { q: "At 30:1 leverage, £100 of margin controls £3,000. The price moves 1% against you. What do you lose?", options: ["£30", "£1", "£3", "£300"], answer: 0, why: "1% of the £3,000 position is £30: 30% of the margin." },
      { q: "Which can't lose more than you put in?", options: ["Real shares", "CFDs", "Spread bets", "All of them can"], answer: 0, why: "Shares bought outright without borrowing can fall to zero, but no further." },
      { q: "What's charged daily on leveraged positions held overnight?", options: ["Financing", "Stamp duty", "Capital gains tax", "Nothing"], answer: 0, why: "Brokers charge interest on the borrowed part of the position for each night it's held." },
      { q: "Where should you check how trading profits are taxed?", options: ["HMRC's current guidance or a qualified adviser", "A trading forum", "Your broker's adverts", "Nowhere: it's always tax-free"], answer: 0, why: "Tax rules change and depend on your circumstances." },
    ],
    task: { kind: "self", text: "Backtest the same strategy on the same market twice, as real shares and as CFD / spread bet, and compare the costs and the result.", go: { page: "backtest", label: "Open Backtest" } },
  },
  {
    week: 12,
    title: "Your trading plan",
    goal: "Write the plan you'll follow, and know the bar a strategy must clear before real money.",
    lessons: [
      {
        title: "What a plan contains",
        body: [
          "A trading plan is a page you write while calm and follow while stressed. It covers: which markets, which strategy and settings, which timeframe, risk per trade, the most at risk at once, what makes you pause, and your review routine.",
          "Keep it short enough to read before every session. If you're tempted to break it, the plan wins; you can change it at the weekly review, never mid-trade.",
        ],
      },
      {
        title: "The graduation bar",
        body: [
          "Before real money is even considered, a strategy should have run on paper long enough to judge: around 40 or more trades, not a few weeks. Its paper results should resemble the backtest (win rate, average R, losing runs, worst fall), your rule score should be consistently high, and the falls should be within what the Monte Carlo check predicted.",
          "For a slow strategy like Breakout 55/20 that can take a couple of years. That's the honest timescale.",
        ],
      },
      {
        title: "Real money, slowly",
        body: [
          "When the time comes, the roadmap's plan is deliberately cautious: real shares first, no leverage, small amounts, confirming each trade yourself, with limits in pounds and a kill switch.",
          "Start smaller than you think, keep the same 1% rule, and expect real fills, emotions and costs to be a little worse than paper. If live results drift from paper, stop and find out why.",
        ],
      },
    ],
    quiz: [
      { q: "When should you change your trading plan?", options: ["At a scheduled review, never mid-trade", "Whenever a trade is losing", "After every win", "Never"], answer: 0, why: "Plans should evolve, but calmly and on schedule, not under the stress of an open trade." },
      { q: "Roughly how many paper trades before judging a strategy?", options: ["40 or more", "5", "10", "One good month"], answer: 0, why: "Fewer trades than that can't tell a real edge from luck." },
      { q: "Paper results show a much lower win rate than the backtest after 50 trades. What next?", options: ["Investigate why before going further", "Go live anyway", "Double the risk", "Ignore it"], answer: 0, why: "A gap between paper and backtest means something differs: costs, fills, the market, or the rules being followed." },
      { q: "What's the plan for the first real-money trades?", options: ["Real shares, no leverage, small amounts, confirming each trade", "CFDs at full leverage", "Copy the paper account's size immediately", "Let it run unattended"], answer: 0, why: "Start where mistakes are cheapest and you stay in control." },
    ],
    task: { kind: "plan", text: "Write your trading plan: markets, strategy and settings, timeframe, risk per trade, most at risk at once, what makes you pause, and your review routine." },
  },
];
