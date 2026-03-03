# -*- coding: utf-8 -*-
"""
md2ttl_v3_fullname.py  –  Markdown → Turtle  (full URI names)
=============================================================

固定路径 (亦可 -i/-o 覆盖)：
    INPUT_MD   = /home/rujia/Data/marker/Arxiv_2022S1_Output/0704.2097/0704.2097.md
    OUTPUT_DIR = /home/rujia/Data/marker
"""

import os, re, html, argparse
from hashlib import md5
from urllib.parse import quote
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Set

import markdown
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS, DC, XSD, OWL, SKOS

# ---------- 路径常量 ----------------------------------------------------------
INPUT_MD = r"/home/rujia/Data/marker/Arxiv_2022S1_Output/0704.2097/0704.2097.md"
OUTPUT_DIR = r"/home/rujia/Data/marker"

# ---------- 命名空间 & 本体常量 ----------------------------------------------
ASKG_DATA = Namespace("https://www.anu.edu.au/data/scholarly/")
ASKG_ONTO = Namespace("https://www.anu.edu.au/onto/scholarly#")
DOMO = Namespace("http://example.org/domo/")

NUMBER_OF_SENTENCES = "numberOfSentences"
HAS_CITATION = "hasCitation"

# ---------- 全局索引 ----------------------------------------------------------
PAPER_INDEX: Dict[str, Dict[str, str]] = {}

# ============================================================================ #
#                              Reference 处理                                   #
# ============================================================================ #
_ref_heading_pat = re.compile(
    r"^(#{1,6})\s*(references?|bibliography|works\s+cited)\s*$", re.I | re.M
)


def extract_reference_block(md: str) -> str:
    for m in _ref_heading_pat.finditer(md):
        start = md.find("\n", m.start())
        if start == -1:
            start = len(md)
        rest = md[start + 1 :]
        nxt = re.search(r"^#{1,6}\s", rest, re.M)
        end = start + 1 + (nxt.start() if nxt else len(rest))
        return md[start + 1 : end].strip()
    return ""


_ref_line_lead_pat = re.compile(r"^\s*(\[\d+\]|\d+[.)])\s*")


def parse_reference_lines(block: str) -> List[Dict]:
    refs = []
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        idx = None
        m = _ref_line_lead_pat.match(ln)
        if m:
            idx = re.sub(r"[^\d]", "", m.group(1))
            ln = ln[m.end() :].strip()

        m_year = re.search(r"\((\d{4})\)", ln)
        year = m_year.group(1) if m_year else ""
        before = ln[: m_year.start()].strip() if m_year else ln
        after = ln[m_year.end() :].strip() if m_year else ""
        authors = before.rstrip(".")
        title = after.split(".")[0].strip() or after
        refs.append({"idx": idx, "authors": authors, "year": year, "title": title})
    return refs


# ---------- Citation 提取 -----------------------------------------------------
_num_pat = re.compile(
    r"\[(\d+(?:\s*[\u2013\u2014\-]\s*\d+)?(?:\s*,\s*\d+(?:\s*[\u2013\u2014\-]\s*\d+)?)*)\]"
)
_auth_pat = re.compile(
    r"(?:^|\W)([A-Z][A-Za-z\-]+)(?:\s+et\s+al\.)?(?:\s+and\s+[A-Z][A-Za-z\-]+)?\s*(?:,|\(|\s)(\d{4})(?:\)|\b)"
)


def expand_num_token(tok: str) -> List[str]:
    out = []
    for part in tok.split(","):
        part = part.strip()
        if re.search(r"[\u2013\u2014\-]", part):
            a, b = re.split(r"[\u2013\u2014\-]", part)
            out.extend(map(str, range(int(a), int(b) + 1)))
        else:
            out.append(part)
    return out


def extract_citations(txt: str) -> List[Tuple[str, str]]:
    cites, seen = [], set()
    for m in _num_pat.finditer(txt):
        for n in expand_num_token(m.group(1)):
            if ("num", n) not in seen:
                cites.append(("num", n))
                seen.add(("num", n))
    for m in _auth_pat.finditer(txt):
        key = f"{m.group(1).lower()}_{m.group(2)}"
        if ("authyear", key) not in seen:
            cites.append(("authyear", key))
            seen.add(("authyear", key))
    return cites


# ============================================================================ #
#                       Markdown → XML (含 numberOfSentences)                  #
# ============================================================================ #
def parse_markdown_structure(md: str):
    lines, secs, cur, buf = md.splitlines(), [], None, []
    for ln in lines:
        m = re.match(r"^(#{1,6})\s+(.+)$", ln)
        if m:
            if cur:
                cur["content"] = "\n".join(buf).strip()
                secs.append(cur)
            cur = {
                "index": len(secs) + 1,
                "level": len(m.group(1)),
                "title": m.group(2).strip(),
            }
            buf = []
        elif cur:
            buf.append(ln)
    if cur:
        cur["content"] = "\n".join(buf).strip()
        secs.append(cur)
    return secs


def clean_text(t: str) -> str:
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


split_paragraphs = lambda c: [p.strip() for p in re.split(r"\n\s*\n", c) if p.strip()]
split_sentences = lambda p: [s for s in re.split(r"(?<=[.!?])\s+", clean_text(p)) if s]


def build_xml(md: str) -> ET.Element:
    root = ET.Element("root")
    for sec in parse_markdown_structure(md):
        sec_el = ET.SubElement(
            root,
            "section",
            ID=str(sec["index"]),
            index=str(sec["index"]),
            level=str(sec["level"]),
        )
        ET.SubElement(sec_el, "heading").text = sec["title"]
        sec_cnt = 0
        for pi, para in enumerate(split_paragraphs(sec["content"]), 1):
            para_el = ET.SubElement(
                sec_el, "paragraph", ID=f"{sec['index']}.{pi}", index=str(pi)
            )
            ET.SubElement(para_el, "text").text = clean_text(para)
            para_cnt = 0
            for si, s in enumerate(split_sentences(para), 1):
                sent_el = ET.SubElement(
                    para_el, "sentence", ID=f"{sec['index']}.{pi}.{si}", index=str(si)
                )
                ET.SubElement(sent_el, "text").text = s
                para_cnt += 1
            para_el.set("numberOfSentences", str(para_cnt))
            sec_cnt += para_cnt
        sec_el.set("numberOfSentences", str(sec_cnt))
    return root


# ============================================================================ #
#                           XML → Turtle                                       #
# ============================================================================ #
def clean_uri(t: str, l=80) -> str:
    b = re.sub(r"[^\w\s-]", "", t).lower().replace(" ", "_")
    b = quote(b)[:l]
    return b or md5(t.encode()).hexdigest()[:12]


def citation_literal(mark, num_map, ay_map, existing):
    typ, key = mark
    ref = num_map.get(key) if typ == "num" else ay_map.get(key)
    if not ref:
        return f"[{key}]" if typ == "num" else key.replace("_", " ")
    pid = None
    for k, info in existing.items():
        if info["title"].lower() == ref["title"].lower() and info.get(
            "year"
        ) == ref.get("year"):
            pid = k
            break
    title, authors = ref["title"], ref["authors"]
    return f"{pid} ⟂ {title} ⟂ {authors}" if pid else f"{title} ⟂ {authors}"


def generate_ttl(xml_root: ET.Element, md: str, out: str, paper_id: str, existing):
    g = Graph()
    g.bind("askg-data", ASKG_DATA)
    g.bind("askg-onto", ASKG_ONTO)
    g.bind("domo", DOMO)
    index_p = URIRef(ASKG_ONTO + "index")
    level_p = URIRef(ASKG_ONTO + "level")
    n_sent_p = URIRef(ASKG_ONTO + NUMBER_OF_SENTENCES)
    has_cit_p = URIRef(ASKG_ONTO + HAS_CITATION)

    paper_uri = URIRef(ASKG_DATA + f"Paper-{clean_uri(paper_id)}")
    paper_title = next(
        (ln[2:].strip() for ln in md.splitlines() if ln.startswith("# ")), paper_id
    )
    g.add((paper_uri, RDF.type, ASKG_ONTO.Paper))
    g.add((paper_uri, DC.title, Literal(paper_title, lang="en")))
    g.add((paper_uri, RDFS.label, Literal(paper_title, lang="en")))

    ref_block = extract_reference_block(md)
    refs = parse_reference_lines(ref_block)
    num_idx, ay_idx = {}, {}
    for r in refs:
        if r["idx"]:
            num_idx[r["idx"]] = r
        if r["authors"] and r["year"]:
            ay_idx[f"{r['authors'].split(',')[0].split()[-1].lower()}_{r['year']}"] = r

    for sec in xml_root.findall("./section"):
        sec_id = sec.get("ID")
        sec_uri = URIRef(ASKG_DATA + f"Paper-{clean_uri(paper_id)}-Section-{sec_id}")
        g.add((sec_uri, RDF.type, ASKG_ONTO.Section))
        g.add((paper_uri, ASKG_ONTO.hasSection, sec_uri))
        g.add((sec_uri, RDFS.label, Literal(f"Section {sec_id}", lang="en")))
        g.add((sec_uri, index_p, Literal(sec_id, datatype=XSD.int)))
        g.add((sec_uri, level_p, Literal(sec.get("level"), datatype=XSD.int)))
        g.add(
            (
                sec_uri,
                n_sent_p,
                Literal(sec.get("numberOfSentences"), datatype=XSD.positiveInteger),
            )
        )
        hd = sec.find("heading")
        if hd is not None:
            g.add((sec_uri, DOMO.Text, Literal(hd.text, lang="en")))
        sec_cit: set[str] = set()

        for para in sec.findall("paragraph"):
            para_id = para.get("ID")
            para_uri = URIRef(
                ASKG_DATA
                + f"Paper-{clean_uri(paper_id)}-Section-{sec_id}-Paragraph-{clean_uri(para_id)}"
            )
            g.add((para_uri, RDF.type, ASKG_ONTO.Paragraph))
            g.add((sec_uri, ASKG_ONTO.hasParagraph, para_uri))
            g.add(
                (
                    para_uri,
                    RDFS.label,
                    Literal(f"Paragraph {para.get('index')}", lang="en"),
                )
            )
            g.add((para_uri, index_p, Literal(para.get("index"), datatype=XSD.int)))
            g.add(
                (
                    para_uri,
                    n_sent_p,
                    Literal(
                        para.get("numberOfSentences"), datatype=XSD.positiveInteger
                    ),
                )
            )
            txt = para.find("text")
            if txt is not None:
                g.add((para_uri, DOMO.Text, Literal(txt.text, lang="en")))
            para_cit: set[str] = set()

            for sent in para.findall("sentence"):
                sent_id = sent.get("ID")
                sent_uri = URIRef(
                    ASKG_DATA
                    + f"Paper-{clean_uri(paper_id)}-Section-{sec_id}"
                    + f"-Paragraph-{clean_uri(para_id)}-Sentence-{clean_uri(sent_id)}"
                )
                g.add((sent_uri, RDF.type, ASKG_ONTO.Sentence))
                g.add((para_uri, ASKG_ONTO.hasSentence, sent_uri))
                g.add(
                    (
                        sent_uri,
                        RDFS.label,
                        Literal(f"Sentence {sent.get('index')}", lang="en"),
                    )
                )
                g.add((sent_uri, index_p, Literal(sent.get("index"), datatype=XSD.int)))
                stext = sent.find("text").text
                g.add((sent_uri, DOMO.Text, Literal(stext, lang="en")))
                for mark in extract_citations(stext):
                    lit = citation_literal(mark, num_idx, ay_idx, existing)
                    if lit not in para_cit:
                        g.add((sent_uri, has_cit_p, Literal(lit)))
                        para_cit.add(lit)
                    if lit not in sec_cit:
                        g.add((para_uri, has_cit_p, Literal(lit)))
                        sec_cit.add(lit)
            for lit in para_cit:
                if lit not in sec_cit:
                    g.add((sec_uri, has_cit_p, Literal(lit)))
                    sec_cit.add(lit)

    g.serialize(out, format="turtle")
    print("✓ TTL saved →", out)


# ============================================================================ #
#                               入口 / CLI                                     #
# ============================================================================ #
def process(md_path: str, out_dir: str, existing: Dict[str, Dict]):
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()
    pid = os.path.splitext(os.path.basename(md_path))[0]
    xml_root = build_xml(md)
    os.makedirs(out_dir, exist_ok=True)
    ttl_path = os.path.join(out_dir, f"{pid}.ttl")
    generate_ttl(xml_root, md, ttl_path, pid, existing)


def main():
    ap = argparse.ArgumentParser("md2ttl_v3_fullname")
    ap.add_argument("-i", "--input", default=INPUT_MD, help="Markdown file")
    ap.add_argument("-o", "--outdir", default=OUTPUT_DIR, help="Output dir")
    args = ap.parse_args()
    existing = {
        # "paper_001":{"title":"Machine Learning Advances","year":"2019","authors":"Smith A."},
        # "paper_002":{"title":"Deep Learning Applications","year":"2020","authors":"Lee B."},
    }
    process(args.input, args.outdir, existing)


if __name__ == "__main__":
    main()
