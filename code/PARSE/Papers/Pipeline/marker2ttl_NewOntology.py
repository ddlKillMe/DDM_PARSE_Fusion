# -*- coding: utf-8 -*-
"""
md2ttl_v3_fullname_refnode.py  –  Markdown → Turtle  (full URI names + Reference nodes)
"""

import os, re, html, argparse
from hashlib import md5
from urllib.parse import quote
import xml.etree.ElementTree as ET
from typing import List, Dict, Set

from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, DC, XSD

# ---------- 路径常量 ----------------------------------------------------------
INPUT_MD   = r"/home/rujia/Data/marker/Arxiv_2022S1_Output/0709.2205/0709.2205.md"
OUTPUT_DIR = r"/home/rujia/Data/marker"

# ---------- 命名空间 ----------------------------------------------------------
ASKG_DATA = Namespace("https://www.anu.edu.au/data/scholarly/")
ASKG_ONTO = Namespace("https://www.anu.edu.au/onto/scholarly#")
DOMO      = Namespace("http://example.org/domo/")

NUMBER_OF_SENTENCES = "numberOfSentences"
HAS_CITATION        = "hasCitation"

# ---------- Reference 解析 ----------------------------------------------------
_ref_heading_pat = re.compile(
    r"^(#{1,6})\s*(references?|bibliography|works\s+cited)\s*$", re.I | re.M
)

_ref_pat = re.compile(r"""
    ^\s*
    (?P<lead>\[\d+\]|\d+[.)])?\s*      # [12]  或 12.
    (?P<authors>.+?)                   # 作者串（贪婪到年份前）
    \s*\(\s*(?P<year>\d{4})\s*\)\.     # (2023).
    \s*
    (?P<title>[^.]+?\.)                # 标题直到下一个句点
""", re.X)

def extract_reference_block(md: str) -> str:
    for m in _ref_heading_pat.finditer(md):
        start = md.find("\n", m.start())
        rest  = md[start + 1:] if start != -1 else ""
        nxt   = re.search(r"^#{1,6}\s", rest, re.M)
        end   = start + 1 + (nxt.start() if nxt else len(rest))
        return md[start + 1:end].strip()
    return ""

def _first_surname(authors: str) -> str:
    # 逗号优先
    if ',' in authors:
        return authors.split(',')[0].strip().split()[0]
    parts = authors.strip().split()
    return parts[0] if len(parts) == 1 else parts[-1]

# # ---------- 1. parse_reference_lines ----------------------------------------
# def parse_reference_lines(block: str) -> List[Dict]:
#     refs: List[Dict] = []
#     for raw in re.split(r'(?:\n|<br\s*/?>)+', block):
#         raw = raw.strip()
#         if not raw:
#             continue
#
#         m = _ref_pat.match(raw)
#         if not m:
#             # ★ fallback：填充所有字段，避免 KeyError
#             refs.append({
#                 "idx":     None,
#                 "authors": "",
#                 "year":    "",
#                 "title":   "",
#                 "raw":     raw
#             })
#             continue
#
#         d = m.groupdict()
#         refs.append({
#             "idx":     re.sub(r"[^\d]", "", d.get("lead") or "") or None,
#             "authors": (d.get("authors") or "").strip(" ."),
#             "year":    d.get("year") or "",
#             "title":   (d.get("title") or "").strip(),
#             "raw":     raw
#         })
#     return refs

# ---------- 1. parse_reference_lines ----------------------------------------
_lead_num_pat = re.compile(r"\s*(?:\[(?P<num>\d+)\]|(?P<num2>\d+)[.)])")

def parse_reference_lines(block: str) -> List[Dict]:
    """
    将参考文献块拆分为行并解析。
    - 无论正则是否完全匹配，都尽量提取行首编号，填充到 idx 字段。
    - 其余字段缺失时留空，避免后续 KeyError。
    """
    refs: List[Dict] = []

    # 按换行或 <br/> 拆分
    for raw in re.split(r'(?:\n|<br\s*/?>)+', block):
        raw = raw.strip()
        if not raw:
            continue

        # 1) 先抓行首编号
        lead_m = _lead_num_pat.match(raw)
        idx_num = (lead_m.group("num") or lead_m.group("num2")) if lead_m else None

        # 2) 再用完整正则解析
        m = _ref_pat.match(raw)
        if m:                                   # 成功解析
            d = m.groupdict()
            refs.append({
                "idx":     idx_num or re.sub(r"[^\d]", "", d.get("lead") or "") or None,
                "authors": (d.get("authors") or "").strip(" ."),
                "year":    d.get("year") or "",
                "title":   (d.get("title") or "").strip(),
                "raw":     raw
            })
        else:                                  # 解析失败：至少保留 idx 与原始行
            refs.append({
                "idx":     idx_num,             # 可能是 None
                "authors": "",
                "year":    "",
                "title":   "",
                "raw":     raw
            })

    return refs


# ---------- 文内 citation 提取 -------------------------------------------------
_num_pat  = re.compile(r"\[(\d+(?:[\u2013\u2014\-]\d+)?(?:,\s*\d+(?:[\u2013\u2014\-]\d+)?)*)\]")
_auth_pat = re.compile(
    r"(?:^|\W)([A-Z][A-Za-z\-]+)(?:\s+et\s+al)?(?:\s+and\s+[A-Z][A-Za-z\-]+)?\s*(?:,|\(|\s)(\d{4})(?:\)|\b)"
)
def _expand_num(tok: str) -> List[str]:
    out = []
    for seg in tok.split(','):
        seg = seg.strip()
        if re.search(r"[\u2013\u2014\-]", seg):
            a, b = re.split(r"[\u2013\u2014\-]", seg)
            out.extend(map(str, range(int(a), int(b) + 1)))
        else:
            out.append(seg)
    return out

def extract_citations(txt: str) -> List[str]:
    cites, seen = [], set()
    for m in _num_pat.finditer(txt):
        for n in _expand_num(m.group(1)):
            if n not in seen:
                cites.append(n); seen.add(n)
    for m in _auth_pat.finditer(txt):
        key = f"{m.group(1).lower()}_{m.group(2)}"
        if key not in seen:
            cites.append(key); seen.add(key)
    return cites

# ---------- Markdown → XML (带句数统计) ---------------------------------------
def parse_markdown_structure(md: str):
    lines, secs, cur, buf = md.splitlines(), [], None, []
    for ln in lines:
        m = re.match(r"^(#{1,6})\s+(.+)$", ln)
        if m:
            if cur:
                cur["content"] = "\n".join(buf).strip(); secs.append(cur)
            cur = {"index": len(secs)+1, "level": len(m.group(1)), "title": m.group(2).strip()}
            buf = []
        elif cur:
            buf.append(ln)
    if cur:
        cur["content"] = "\n".join(buf).strip(); secs.append(cur)
    return secs

def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()

split_paragraphs = lambda c: [p.strip() for p in re.split(r"\n\s*\n", c) if p.strip()]
split_sentences  = lambda p: [s for s in re.split(r"(?<=[.!?])\s+", clean_text(p)) if s]

def build_xml(md: str) -> ET.Element:
    root = ET.Element("root")
    for sec in parse_markdown_structure(md):
        sec_el = ET.SubElement(root, "section", ID=str(sec["index"]),
                               index=str(sec["index"]), level=str(sec["level"]))
        ET.SubElement(sec_el, "heading").text = sec["title"]
        sec_cnt = 0
        for pi, para in enumerate(split_paragraphs(sec["content"]), 1):
            para_el = ET.SubElement(sec_el, "paragraph",
                                    ID=f"{sec['index']}.{pi}", index=str(pi))
            ET.SubElement(para_el, "text").text = clean_text(para)
            for cit in extract_citations(para):
                ET.SubElement(para_el, "citation").text = cit
            para_cnt = 0
            for si, s in enumerate(split_sentences(para), 1):
                sent_el = ET.SubElement(para_el, "sentence",
                                        ID=f"{sec['index']}.{pi}.{si}", index=str(si))
                ET.SubElement(sent_el, "text").text = s
                for cit in extract_citations(s):
                    ET.SubElement(sent_el, "citation").text = cit
                para_cnt += 1
            para_el.set("numberOfSentences", str(para_cnt)); sec_cnt += para_cnt
        sec_el.set("numberOfSentences", str(sec_cnt))
    return root

# ---------- URI utils ---------------------------------------------------------
def clean_uri(t: str, limit=80) -> str:
    base = re.sub(r"[^\w\s-]", "", t).lower().replace(" ", "_")
    return quote(base)[:limit] or md5(t.encode()).hexdigest()[:12]

# ---------- 主转换 ------------------------------------------------------------
def generate_ttl(xml_root: ET.Element, md: str, out: str, paper_id: str):
    g = Graph()
    for p, ns in [("askg-data", ASKG_DATA), ("askg-onto", ASKG_ONTO), ("domo", DOMO)]:
        g.bind(p, ns)
    g.bind("rdfs", RDFS); g.bind("dc", DC); g.bind("xsd", XSD)

    idx_p    = URIRef(ASKG_ONTO + "index")
    lvl_p    = URIRef(ASKG_ONTO + "level")
    n_sent_p = URIRef(ASKG_ONTO + NUMBER_OF_SENTENCES)
    has_cit  = URIRef(ASKG_ONTO + HAS_CITATION)
    author_p = URIRef(ASKG_ONTO + "author")

    # ---- Paper ----
    paper_uri   = URIRef(ASKG_DATA + f"Paper-{clean_uri(paper_id)}")
    paper_title = next((l[2:].strip() for l in md.splitlines() if l.startswith("# ")), paper_id)
    g.add((paper_uri, RDF.type, ASKG_ONTO.Paper))
    g.add((paper_uri, DC.title,  Literal(paper_title, lang="en")))
    g.add((paper_uri, RDFS.label, Literal(paper_title, lang="en")))

    # ---- References ----
    ref_block = extract_reference_block(md)
    refs      = parse_reference_lines(ref_block)
    num_idx: Dict[str, URIRef] = {}
    ay_idx:  Dict[str, URIRef] = {}

    for i, ref in enumerate(refs, 1):
        ref_uri = URIRef(ASKG_DATA + f"Paper-{clean_uri(paper_id)}-Reference-{i}")
        g.add((ref_uri, RDF.type, ASKG_ONTO.Reference))
        g.add((ref_uri, RDFS.label, Literal(f"Reference {i}", lang="en")))
        g.add((ref_uri, DOMO.Text, Literal(ref["raw"], lang="en")))

        # ★ 使用 .get() 并确保字段存在
        authors = ref.get("authors", "")
        year    = ref.get("year", "")

        if re.search(r"[A-Za-z]", authors):
            g.add((ref_uri, author_p, Literal(authors, lang="en")))
            if year:
                g.add((ref_uri, DC.date, Literal(year, datatype=XSD.gYear)))
                surname = _first_surname(authors).lower()
                ay_idx[f"{surname}_{year}"] = ref_uri

        idx_num = ref.get("idx")
        if idx_num:
            num_idx[idx_num] = ref_uri

    # ---- Walk XML ----
    for sec in xml_root.findall("./section"):
        sid     = sec.get("ID")
        sec_uri = URIRef(ASKG_DATA + f"Paper-{clean_uri(paper_id)}-Section-{sid}")
        g.add((sec_uri, RDF.type, ASKG_ONTO.Section))
        g.add((paper_uri, ASKG_ONTO.hasSection, sec_uri))
        g.add((sec_uri, RDFS.label, Literal(f"Section {sid}", lang="en")))
        g.add((sec_uri, idx_p,  Literal(sid, datatype=XSD.int)))
        g.add((sec_uri, lvl_p,  Literal(sec.get("level"), datatype=XSD.int)))
        g.add((sec_uri, n_sent_p, Literal(sec.get(NUMBER_OF_SENTENCES), datatype=XSD.positiveInteger)))
        hd = sec.find("heading");  hd_text = hd.text if hd is not None else ""
        g.add((sec_uri, DOMO.Text, Literal(hd_text, lang="en")))

        sec_seen: Set[URIRef] = set()

        for para in sec.findall("paragraph"):
            pid      = para.get("ID")
            para_uri = URIRef(ASKG_DATA + f"Paper-{clean_uri(paper_id)}-Section-{sid}-Paragraph-{clean_uri(pid)}")
            g.add((para_uri, RDF.type, ASKG_ONTO.Paragraph))
            g.add((sec_uri, ASKG_ONTO.hasParagraph, para_uri))
            g.add((para_uri, RDFS.label, Literal(f"Paragraph {para.get('index')}", lang="en")))
            g.add((para_uri, idx_p,  Literal(para.get("index"), datatype=XSD.int)))
            g.add((para_uri, n_sent_p, Literal(para.get(NUMBER_OF_SENTENCES), datatype=XSD.positiveInteger)))
            p_txt = para.findtext("text", "")
            g.add((para_uri, DOMO.Text, Literal(p_txt, lang="en")))

            para_seen: Set[URIRef] = set()

            def _cite(token: str):
                if token.isdigit():
                    return num_idx.get(token)
                return ay_idx.get(token.lower())

            for tok in [c.text for c in para.findall("citation")]:
                obj = _cite(tok) or Literal(tok.replace("_", " "))
                if obj not in para_seen:
                    g.add((para_uri, has_cit, obj)); para_seen.add(obj)
                if obj not in sec_seen:
                    g.add((sec_uri, has_cit, obj));  sec_seen.add(obj)

            for sent in para.findall("sentence"):
                s_id     = sent.get("ID")
                sent_uri = URIRef(
                    ASKG_DATA +
                    f"Paper-{clean_uri(paper_id)}-Section-{sid}-Paragraph-{clean_uri(pid)}-Sentence-{clean_uri(s_id)}")
                g.add((sent_uri, RDF.type, ASKG_ONTO.Sentence))
                g.add((para_uri, ASKG_ONTO.hasSentence, sent_uri))
                g.add((sent_uri, RDFS.label, Literal(f"Sentence {sent.get('index')}", lang="en")))
                g.add((sent_uri, idx_p, Literal(sent.get('index'), datatype=XSD.int)))
                g.add((sent_uri, DOMO.Text, Literal(sent.findtext("text"), lang="en")))

                sent_seen: Set[URIRef] = set()
                for tok in [c.text for c in sent.findall("citation")]:
                    obj = _cite(tok) or Literal(tok.replace("_", " "))
                    if obj not in sent_seen:
                        g.add((sent_uri, has_cit, obj));   sent_seen.add(obj)
                    if obj not in para_seen:
                        g.add((para_uri, has_cit, obj));   para_seen.add(obj)
                    if obj not in sec_seen:
                        g.add((sec_uri, has_cit, obj));    sec_seen.add(obj)

    g.serialize(out, format="turtle")
    print("✓ TTL saved →", out)

# ---------- CLI --------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input",  default=INPUT_MD,   help="Markdown file")
    ap.add_argument("-o", "--outdir", default=OUTPUT_DIR, help="Output directory")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        md = f.read()
    xml_root = build_xml(md)
    os.makedirs(args.outdir, exist_ok=True)
    pid = os.path.splitext(os.path.basename(args.input))[0]
    generate_ttl(xml_root, md, os.path.join(args.outdir, f"{pid}.ttl"), pid)

if __name__ == "__main__":
    main()
