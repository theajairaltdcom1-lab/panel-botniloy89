"""Country dial-code -> flag/ISO (from D:\\open code test)."""

COUNTRIES = {
    "93": ("AF", "Afghanistan"), "355": ("AL", "Albania"), "213": ("DZ", "Algeria"),
    "1": ("US", "USA/Canada"), "61": ("AU", "Australia"),
    "43": ("AT", "Austria"), "32": ("BE", "Belgium"), "55": ("BR", "Brazil"),
    "359": ("BG", "Bulgaria"), "56": ("CL", "Chile"),
    "86": ("CN", "China"), "57": ("CO", "Colombia"), "385": ("HR", "Croatia"),
    "420": ("CZ", "Czechia"), "45": ("DK", "Denmark"), "20": ("EG", "Egypt"),
    "372": ("EE", "Estonia"), "358": ("FI", "Finland"), "33": ("FR", "France"),
    "49": ("DE", "Germany"), "30": ("GR", "Greece"), "852": ("HK", "Hong Kong"),
    "36": ("HU", "Hungary"), "91": ("IN", "India"),
    "62": ("ID", "Indonesia"), "98": ("IR", "Iran"), "964": ("IQ", "Iraq"),
    "353": ("IE", "Ireland"), "972": ("IL", "Israel"), "39": ("IT", "Italy"),
    "81": ("JP", "Japan"), "254": ("KE", "Kenya"), "7": ("RU", "Russia"),
    "965": ("KW", "Kuwait"), "371": ("LV", "Latvia"), "961": ("LB", "Lebanon"),
    "218": ("LY", "Libya"), "370": ("LT", "Lithuania"), "60": ("MY", "Malaysia"),
    "52": ("MX", "Mexico"), "31": ("NL", "Netherlands"), "64": ("NZ", "New Zealand"),
    "234": ("NG", "Nigeria"), "47": ("NO", "Norway"),
    "95": ("MM", "Myanmar"),
    "968": ("OM", "Oman"), "92": ("PK", "Pakistan"), "880": ("BD", "Bangladesh"),
    "977": ("NP", "Nepal"), "855": ("KH", "Cambodia"), "856": ("LA", "Laos"),
    "994": ("AZ", "Azerbaijan"), "995": ("GE", "Georgia"), "996": ("KG", "Kyrgyzstan"),
    "998": ("UZ", "Uzbekistan"), "992": ("TJ", "Tajikistan"), "993": ("TM", "Turkmenistan"),
    "374": ("AM", "Armenia"), "375": ("BY", "Belarus"), "373": ("MD", "Moldova"),
    "967": ("YE", "Yemen"), "962": ("JO", "Jordan"), "970": ("PS", "Palestine"),
    "233": ("GH", "Ghana"), "251": ("ET", "Ethiopia"), "252": ("SO", "Somalia"),
    "255": ("TZ", "Tanzania"), "256": ("UG", "Uganda"), "221": ("SN", "Senegal"),
    "223": ("ML", "Mali"), "224": ("GN", "Guinea"), "225": ("CI", "Ivory Coast"),
    "227": ("NE", "Niger"), "228": ("TG", "Togo"), "229": ("BJ", "Benin"),
    "230": ("MU", "Mauritius"), "231": ("LR", "Liberia"), "237": ("CM", "Cameroon"),
    "241": ("GA", "Gabon"), "242": ("CG", "Congo"), "243": ("CD", "DR Congo"),
    "244": ("AO", "Angola"), "248": ("SC", "Seychelles"), "249": ("SD", "Sudan"),
    "250": ("RW", "Rwanda"), "257": ("BI", "Burundi"), "258": ("MZ", "Mozambique"),
    "591": ("BO", "Bolivia"), "593": ("EC", "Ecuador"), "595": ("PY", "Paraguay"),
    "502": ("GT", "Guatemala"), "503": ("SV", "El Salvador"), "504": ("HN", "Honduras"),
    "505": ("NI", "Nicaragua"), "506": ("CR", "Costa Rica"), "507": ("PA", "Panama"),
    "509": ("HT", "Haiti"), "51": ("PE", "Peru"),
    "63": ("PH", "Philippines"), "48": ("PL", "Poland"), "351": ("PT", "Portugal"),
    "974": ("QA", "Qatar"), "40": ("RO", "Romania"),
    "966": ("SA", "Saudi Arabia"), "381": ("RS", "Serbia"),
    "65": ("SG", "Singapore"), "421": ("SK", "Slovakia"), "27": ("ZA", "South Africa"),
    "82": ("KR", "South Korea"), "34": ("ES", "Spain"), "94": ("LK", "Sri Lanka"),
    "46": ("SE", "Sweden"), "41": ("CH", "Switzerland"), "963": ("SY", "Syria"),
    "886": ("TW", "Taiwan"), "66": ("TH", "Thailand"),
    "90": ("TR", "Turkey"), "971": ("AE", "UAE"), "380": ("UA", "Ukraine"),
    "44": ("GB", "United Kingdom"), "598": ("UY", "Uruguay"),
    "58": ("VE", "Venezuela"), "84": ("VN", "Vietnam"),
    "260": ("ZM", "Zambia"), "263": ("ZW", "Zimbabwe"),
}


def iso2_flag(iso: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord("A")) for c in iso)


def country_info(number: str):
    """Returns (flag, iso, name, dial)."""
    d = "".join(ch for ch in (number or "") if ch.isdigit())
    for length in (3, 2, 1):
        dial = d[:length]
        info = COUNTRIES.get(dial)
        if info:
            iso, name = info
            return iso2_flag(iso), iso, name, dial
    return "🌐", "", "Unknown", ""


_ISO_CACHE = None


def iso_info(iso: str):
    """ISO code -> (flag, name)."""
    global _ISO_CACHE
    if _ISO_CACHE is None:
        _ISO_CACHE = {}
        for _dial, (_iso, _name) in COUNTRIES.items():
            _ISO_CACHE.setdefault(_iso, (_name, _dial))
    if not iso or iso == "??":
        return "🌍", "Unknown"
    hit = _ISO_CACHE.get(iso.upper())
    if not hit:
        return "🌍", iso
    return iso2_flag(iso), hit[0]


def service_emoji(cli: str) -> str:
    c = (cli or "").strip().lower()
    if not c:
        return "📩"
    if "face" in c or c == "fb":
        return "📘"
    if "whats" in c:
        return "💚"
    if "tele" in c:
        return "✈️"
    if "goog" in c:
        return "🔵"
    if c == "imo" or "imo" in c:
        return "💛"
    if "tiktok" in c or "tik tok" in c:
        return "🎵"
    if "insta" in c:
        return "📸"
    if "viber" in c:
        return "📞"
    if "snap" in c:
        return "👻"
    if "apple" in c:
        return "🍎"
    if "yahoo" in c:
        return "🟣"
    if "micro" in c or "outlook" in c or "hotmail" in c:
        return "📧"
    return "📩"
