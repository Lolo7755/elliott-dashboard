"""
Chancen-Finder: automatischer Vorfilter über große US- und deutsche Aktien außerhalb der Watchlist.

Zwei Muster (nur Kursdaten der letzten 12 Monate, ein Sammel-Download):
  Rücksetzer im Trend: Aufwärtstrend (Kurs und 50-Tage-Linie über der 200-Tage-Linie),
                       starkes Halbjahr, Kurs gerade zurück an der 50-Tage-Linie, RSI abgekühlt.
  Vor dem Ausbruch:    Kurs knapp unter dem 52-Wochen-Hoch, enge Seitwärtsphase der letzten
                       4 Wochen (Schwankung zieht sich zusammen), über der 50-Tage-Linie.
Treffer sind Kandidaten, keine Kaufsignale – erst nach der vollen Elliott-Analyse kaufen.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

UNIVERSUM = """
AAPL Apple|MSFT Microsoft|NVDA Nvidia|AMZN Amazon|GOOGL Alphabet|META Meta Platforms|TSLA Tesla|AVGO Broadcom|BRK-B Berkshire Hathaway
JPM JPMorgan Chase|V Visa|MA Mastercard|UNH UnitedHealth|XOM Exxon Mobil|LLY Eli Lilly|JNJ Johnson & Johnson|PG Procter & Gamble
HD Home Depot|COST Costco|ABBV AbbVie|MRK Merck & Co.|ORCL Oracle|CVX Chevron|KO Coca-Cola|PEP PepsiCo|BAC Bank of America
NFLX Netflix|CRM Salesforce|AMD Advanced Micro Devices|ADBE Adobe|TMO Thermo Fisher|WMT Walmart|MCD McDonald's|CSCO Cisco
ACN Accenture|ABT Abbott|LIN Linde|DHR Danaher|INTU Intuit|TXN Texas Instruments|QCOM Qualcomm|DIS Walt Disney|WFC Wells Fargo
PM Philip Morris|VZ Verizon|IBM IBM|AMGN Amgen|CAT Caterpillar|NOW ServiceNow|GE GE Aerospace|ISRG Intuitive Surgical|UBER Uber
SPGI S&P Global|GS Goldman Sachs|MS Morgan Stanley|RTX RTX|HON Honeywell|INTC Intel|BKNG Booking Holdings|LOW Lowe's|UNP Union Pacific
T AT&T|PFE Pfizer|AMAT Applied Materials|BLK BlackRock|SYK Stryker|AXP American Express|ELV Elevance Health|DE Deere|LMT Lockheed Martin
TJX TJX Companies|BMY Bristol-Myers Squibb|SCHW Charles Schwab|C Citigroup|MDT Medtronic|ADP ADP|PLD Prologis|GILD Gilead
VRTX Vertex Pharmaceuticals|MMC Marsh McLennan|LRCX Lam Research|ADI Analog Devices|PANW Palo Alto Networks|CB Chubb|MU Micron
SBUX Starbucks|REGN Regeneron|KLAC KLA|BA Boeing|SO Southern Company|MDLZ Mondelez|CI Cigna|ANET Arista Networks|KKR KKR
NKE Nike|BX Blackstone|SNPS Synopsys|CDNS Cadence Design|CME CME Group|ZTS Zoetis|DUK Duke Energy|ICE Intercontinental Exchange
MO Altria|SHW Sherwin-Williams|PH Parker-Hannifin|CL Colgate-Palmolive|TT Trane|EQIX Equinix|APH Amphenol|MCK McKesson
CMG Chipotle|WM Waste Management|PYPL PayPal|USB U.S. Bancorp|PNC PNC Financial|GD General Dynamics|NOC Northrop Grumman
ORLY O'Reilly Automotive|MAR Marriott|ABNB Airbnb|CRWD CrowdStrike|FTNT Fortinet|MRVL Marvell|CEG Constellation Energy|ITW Illinois Tool Works
EMR Emerson|ECL Ecolab|CSX CSX|FDX FedEx|NSC Norfolk Southern|APD Air Products|MMM 3M|TDG TransDigm|AJG Arthur J. Gallagher
ROP Roper|ADSK Autodesk|HCA HCA Healthcare|TGT Target|AZO AutoZone|PCAR Paccar|COF Capital One|TFC Truist|AFL Aflac|MET MetLife
NEM Newmont|FCX Freeport-McMoRan|SLB Schlumberger|EOG EOG Resources|COP ConocoPhillips|PSX Phillips 66|MPC Marathon Petroleum
OXY Occidental|VLO Valero|WMB Williams|KMI Kinder Morgan|OKE ONEOK|NEE NextEra Energy|D Dominion|AEP American Electric Power
SRE Sempra|EXC Exelon|VST Vistra|NRG NRG Energy|GEV GE Vernova|ETN Eaton|URI United Rentals|PWR Quanta Services|CARR Carrier
JCI Johnson Controls|HWM Howmet|AXON Axon|LHX L3Harris|HII Huntington Ingalls|DASH DoorDash|SPOT Spotify|SHOP Shopify|PLTR Palantir
SNOW Snowflake|DDOG Datadog|NET Cloudflare|ZS Zscaler|MDB MongoDB|TEAM Atlassian|WDAY Workday|TTD Trade Desk|HUBS HubSpot|OKTA Okta
COIN Coinbase|HOOD Robinhood|XYZ Block|AFRM Affirm|SOFI SoFi|RBLX Roblox|U Unity|EA Electronic Arts|TTWO Take-Two|NTES NetEase
SMCI Super Micro Computer|DELL Dell|HPQ HP|HPE Hewlett Packard Enterprise|WDC Western Digital|STX Seagate|NTAP NetApp|PSTG Pure Storage
ON ON Semiconductor|NXPI NXP|MCHP Microchip|MPWR Monolithic Power|TER Teradyne|ENTG Entegris|ASML ASML|TSM TSMC|ARM Arm Holdings
COHR Coherent|LITE Lumentum|CIEN Ciena|VRT Vertiv|ALAB Astera Labs|CRDO Credo|APP AppLovin|IONQ IonQ|RKLB Rocket Lab
DXCM Dexcom|IDXX Idexx|EW Edwards Lifesciences|BSX Boston Scientific|BDX Becton Dickinson|ZBH Zimmer Biomet|RMD ResMed|PODD Insulet
MRNA Moderna|BIIB Biogen|ILMN Illumina|HUM Humana|CVS CVS Health|CNC Centene|MOH Molina|IQV IQVIA|A Agilent|WAT Waters
NVO Novo Nordisk|AZN AstraZeneca|SNY Sanofi|GSK GSK|NVS Novartis|UL Unilever|SAP SAP (ADR)|SONY Sony|TM Toyota|BABA Alibaba|PDD PDD Holdings
JD JD.com|BIDU Baidu|MELI MercadoLibre|NU Nu Holdings|SE Sea Limited|CPNG Coupang|LULU Lululemon|DECK Deckers|ONON On Holding
CROX Crocs|ULTA Ulta Beauty|EL Estee Lauder|ROST Ross Stores|DG Dollar General|DLTR Dollar Tree|KR Kroger|SYY Sysco|KHC Kraft Heinz
GIS General Mills|HSY Hershey|STZ Constellation Brands|MNST Monster Beverage|KDP Keurig Dr Pepper|YUM Yum Brands|DPZ Domino's|CMI Cummins
F Ford|GM General Motors|RIVN Rivian|LCID Lucid|HOG Harley-Davidson|DAL Delta Air Lines|UAL United Airlines|AAL American Airlines|LUV Southwest
CCL Carnival|RCL Royal Caribbean|NCLH Norwegian Cruise|EXPE Expedia|HLT Hilton|LVS Las Vegas Sands|WYNN Wynn Resorts|MGM MGM Resorts
O Realty Income|AMT American Tower|CCI Crown Castle|SPG Simon Property|PSA Public Storage|WELL Welltower|DLR Digital Realty|VICI VICI Properties
ALL Allstate|PGR Progressive|TRV Travelers|AIG AIG|PRU Prudential|HIG Hartford|MCO Moody's|MSCI MSCI|NDAQ Nasdaq|FIS FIS|FI Fiserv|GPN Global Payments
DHI D.R. Horton|LEN Lennar|PHM PulteGroup|NVR NVR|BLDR Builders FirstSource|MLM Martin Marietta|VMC Vulcan Materials|NUE Nucor|STLD Steel Dynamics
DOW Dow|DD DuPont|LYB LyondellBasell|CF CF Industries|MOS Mosaic|ALB Albemarle|FSLR First Solar|ENPH Enphase|SEDG SolarEdge|PLUG Plug Power
SAP.DE SAP|SIE.DE Siemens|ALV.DE Allianz|DTE.DE Deutsche Telekom|AIR.DE Airbus|MUV2.DE Munich Re|MBG.DE Mercedes-Benz|BMW.DE BMW
VOW3.DE Volkswagen|P911.DE Porsche|PAH3.DE Porsche Holding|BAS.DE BASF|BAYN.DE Bayer|IFX.DE Infineon|RHM.DE Rheinmetall|DBK.DE Deutsche Bank
CBK.DE Commerzbank|DB1.DE Deutsche Börse|DHL.DE DHL Group|EOAN.DE E.ON|RWE.DE RWE|ADS.DE Adidas|PUM.DE Puma|HEN3.DE Henkel|BEI.DE Beiersdorf
MRK.DE Merck KGaA|FRE.DE Fresenius|FME.DE Fresenius Medical Care|SHL.DE Siemens Healthineers|ENR.DE Siemens Energy|MTX.DE MTU Aero Engines
HNR1.DE Hannover Rück|VNA.DE Vonovia|CON.DE Continental|DTG.DE Daimler Truck|SY1.DE Symrise|ZAL.DE Zalando|HEI.DE Heidelberg Materials
QIA.DE Qiagen|BNR.DE Brenntag|SRT3.DE Sartorius|G1A.DE GEA|HAG.DE Hensoldt|R3NK.DE Renk|TKA.DE Thyssenkrupp|LHA.DE Lufthansa
TUI1.DE TUI|DHER.DE Delivery Hero|AIXA.DE Aixtron|NEM.DE Nemetschek|SAX.DE Ströer|EVK.DE Evonik|LEG.DE LEG Immobilien|TAG.DE TAG Immobilien
KGX.DE Kion|KBX.DE Knorr-Bremse|RAA.DE Rational|CTS.DE CTS Eventim|SDF.DE K+S|FRA.DE Fraport|BC8.DE Bechtle|HFG.DE HelloFresh|S92.DE SMA Solar
NDX1.DE Nordex|1COV.DE Covestro|WCH.DE Wacker Chemie|JEN.DE Jenoptik|SMHN.DE Süss MicroTec|EVT.DE Evotec|TMV.DE TeamViewer|AFX.DE Carl Zeiss Meditec
"""


def universum() -> list[tuple[str, str]]:
    out = []
    for teil in UNIVERSUM.replace("\n", "|").split("|"):
        teil = teil.strip()
        if teil:
            sym, _, name = teil.partition(" ")
            out.append((sym, name.strip() or sym))
    return list(dict.fromkeys(out))


def _rsi(c: pd.Series, n: int = 14) -> float:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    v = 100 - 100 / (1 + rs)
    return float(v.iloc[-1]) if v.notna().any() else 50.0


def _laden(symbole: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    daten = {}
    for k in range(0, len(symbole), 80):
        teil = symbole[k:k + 80]
        try:
            raw = yf.download(teil, period="1y", interval="1d", group_by="ticker", auto_adjust=True,
                              threads=True, progress=False)
        except Exception as e:
            print(f"Chancen-Finder: Download-Fehler {e}")
            continue
        for s in teil:
            try:
                df = raw[s] if len(teil) > 1 else raw
                df = df.dropna(subset=["Close"])
                if len(df) >= 210:
                    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
                    daten[s] = df
            except Exception:
                pass
    return daten


def suchen(watchlist: set[str], n: int = 12) -> dict:
    from analyzer.elliott import analyze

    uni = universum()
    namen = dict(uni)
    daten = _laden([s for s, _ in uni])
    rueck, ausbr = [], []
    for sym, df in daten.items():
        c = df["Close"]
        last = float(c.iloc[-1])
        sma50, sma200 = float(c.rolling(50).mean().iloc[-1]), float(c.rolling(200).mean().iloc[-1])
        p6 = last / float(c.iloc[-127]) - 1 if len(c) > 127 else 0
        p1 = last / float(c.iloc[-22]) - 1 if len(c) > 22 else 0
        rsi = _rsi(c)
        hoch = float(df["High"].iloc[-252:].max())
        ab50 = last / sma50 - 1
        abh = last / hoch - 1
        r20 = df.iloc[-20:]
        enge = float((r20["High"].max() - r20["Low"].min()) / last)
        basis = {"symbol": sym, "name": namen.get(sym, sym), "kurs": round(last, 2),
                 "currency": "EUR" if sym.endswith(".DE") else "USD",
                 "monat_pct": round(p1 * 100, 1), "halbjahr_pct": round(p6 * 100, 1), "rsi": round(rsi),
                 "abstand_sma50_pct": round(ab50 * 100, 1), "abstand_hoch_pct": round(abh * 100, 1),
                 "enge_pct": round(enge * 100, 1), "in_watchlist": sym in watchlist}
        aufwaerts = last > sma200 and sma50 > sma200
        if aufwaerts and p6 >= 0.15 and -0.03 <= ab50 <= 0.03 and 33 <= rsi <= 55:
            pkt = min(p6, 1.0) * 40 + (1 - abs(ab50) / 0.03) * 30 + (55 - rsi) / 22 * 30
            rueck.append({**basis, "punkte": round(pkt), "muster": "ruecksetzer"})
        if last > sma50 and sma50 > sma200 and -0.05 <= abh <= -0.003 and enge <= 0.12:
            pkt = (1 - abs(abh) / 0.05) * 40 + (1 - enge / 0.12) * 40 + min(max(p6, 0), 0.6) / 0.6 * 20
            ausbr.append({**basis, "punkte": round(pkt), "muster": "ausbruch"})
    rueck.sort(key=lambda x: -x["punkte"])
    ausbr.sort(key=lambda x: -x["punkte"])
    rueck, ausbr = rueck[:n], ausbr[:n]
    for x in rueck + ausbr:  # kurze Elliott-Einordnung (Tageschart) für die Treffer
        try:
            k = analyze(daten[x["symbol"]], x["symbol"], x["name"], x["currency"], horizon="kurz")
            x["elliott_kurz"] = {"status": k["status"], "ampel": k["ampel"], "zone_oben": k["zone"]["oben"],
                                 "zone_unten": k["zone"]["unten"], "stopp": k["zone"]["invalidierung"]}
        except Exception:
            x["elliott_kurz"] = None
    return {"geprueft": len(daten), "universum": len(uni), "ruecksetzer": rueck, "ausbruch": ausbr}
