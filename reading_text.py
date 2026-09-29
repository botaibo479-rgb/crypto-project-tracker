"""Readable translation input; the separately stored original stays unchanged."""
import re
from html.parser import HTMLParser

class Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
        if tag in ('br', 'p', 'div', 'li') and not self.hidden: self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li') and not self.hidden: self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

def readable(text):
    text=re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    # Only interpret actual common markup; keep comparisons such as x < 5.
    if not re.search(r'</?(?:br|p|div|span|a|b|strong|em|i|ul|ol|li|script|style)\b|&(?:amp|lt|gt|quot|#\w+);', text, re.I):
        return text
    parser = Reader()
    parser.feed(text)
    return re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip()

# Preserve exact product names and bare domains that otherwise become ordinary words.
EXTRA = re.compile(r'\b(?:NEAR Intents|Brave Leo|Brave Wallet|Brave|Hyperliquid|Nightshade)\b|\b(?:[a-zA-Z0-9-]+\.)+(?:com|org|io|ai|network|foundation)(?:/[^\s<>]*)?', re.I)
BASE = r'https?://[^\s<>]+|@[A-Za-z0-9_]+|\$[A-Za-z][A-Za-z0-9]*\b|\b(?:SOON|NEAR|PHA|NIL|Nillion|Phala|Nightside|Arbitrum|Spark)\b'
PROTECTED = re.compile(r'https?://[^\s<>]+|'+'(?i:'+EXTRA.pattern+')|'+BASE)

def translation_version(text):
    if re.search(r'\bagents?\b',text,re.I):return 'v5:'
    if re.search(r'\b(?:open interest|funding rate|token unlock|fully diluted valuation)\b',text,re.I):return 'v4:'
    return 'v3:' if readable(text) != text or EXTRA.search(text) or re.search(r'\$[A-Za-z]', text) else 'v2:'

def chunks(text, limit=2200):
    """Never split the placeholder used to protect names and links."""
    while len(text) > limit:
        cut = limit
        for match in re.finditer(r'ZXQKEEP\d+QXZ', text):
            if match.start() < cut < match.end():
                cut = match.start()
                break
        yield text[:cut]
        text = text[cut:]
    if text: yield text


TERMS = {'agents':'智能体','agent':'智能体','open interest':'持仓量（OI）','funding rate':'资金费率','token unlock':'代币解锁','fully diluted valuation':'完全稀释估值（FDV）'}
def standard_terms(text):
    """Normalize known technical phrases without modifying stored originals."""
    return re.sub(r'\b(?:'+ '|'.join(re.escape(k) for k in TERMS)+r')\b',lambda m:TERMS[m.group().lower()],text,flags=re.I)
