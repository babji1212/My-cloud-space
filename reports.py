"""Data analysis helpers for R K LITTLE BUDS - pure functions that work on lists of records."""
from collections import defaultdict


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def ay_of(d):
    """Academic year (June to May) of a date string 'YYYY-MM-DD' or 'YYYY-MM'."""
    try:
        y, m = int(str(d)[:4]), int(str(d)[5:7])
    except (TypeError, ValueError):
        return None
    return f"{y}-{(y + 1) % 100:02d}" if m >= 6 else f"{y - 1}-{y % 100:02d}"


def in_year(d, ay):
    return not ay or ay_of(d or "") == ay


def pct(got, mx):
    return round(got / mx * 100, 1) if mx else None


def _rank(rows, key="pct"):
    last, pos = None, 0
    for i, r in enumerate(rows, 1):
        if r[key] != last:
            pos, last = i, r[key]
        r["rank"] = pos if r[key] is not None else None


def class_exam(students, exams, cls, exam, ay, pass_mark):
    names = {str(s["id"]): s for s in students}
    per, subjects = {}, []
    for r in exams:
        if r.get("cls") != cls or r.get("exam") != exam or not in_year(r.get("date"), ay):
            continue
        sid = str(r.get("sid"))
        s = names.get(sid, {})
        d = per.setdefault(sid, dict(sid=sid, name=s.get("name") or r.get("student", ""), roll=s.get("roll", ""), subj={}, got=0.0, mx=0.0))
        sub = r.get("subject", "")
        if sub not in subjects:
            subjects.append(sub)
        ab = r.get("attended") == "Absent"
        d["subj"][sub] = dict(got=num(r.get("marks")), mx=num(r.get("max")), absent=ab)
        if not ab:
            d["got"] += num(r.get("marks"))
            d["mx"] += num(r.get("max"))
    rows = list(per.values())
    for d in rows:
        d["pct"] = pct(d["got"], d["mx"])
        d["fails"] = [s for s, v in d["subj"].items() if not v["absent"] and v["mx"] and v["got"] / v["mx"] * 100 < pass_mark]
        d["passed"] = bool(d["mx"]) and not d["fails"]
    rows.sort(key=lambda d: (-(d["pct"] if d["pct"] is not None else -1), d["name"]))
    _rank(rows)
    sstats = []
    for sub in subjects:
        vals = [v["got"] / v["mx"] * 100 for d in rows for s, v in d["subj"].items() if s == sub and not v["absent"] and v["mx"]]
        sstats.append(dict(name=sub, n=len(vals), avg=round(sum(vals) / len(vals), 1) if vals else None,
                           hi=round(max(vals), 1) if vals else None, lo=round(min(vals), 1) if vals else None,
                           pass_pct=round(sum(1 for v in vals if v >= pass_mark) / len(vals) * 100) if vals else None))
    ps = [d["pct"] for d in rows if d["pct"] is not None]
    stats = dict(n=len(rows), avg=round(sum(ps) / len(ps), 1) if ps else None, hi=max(ps) if ps else None, lo=min(ps) if ps else None,
                 pass_pct=round(sum(1 for d in rows if d["passed"]) / len(rows) * 100) if rows else None,
                 passed=sum(1 for d in rows if d["passed"]), failed=sum(1 for d in rows if not d["passed"]))
    return dict(rows=rows, subjects=subjects, subj_stats=sstats, stats=stats)


def exam_groups(exams, ay):
    """sid -> list of (date, exam_name, pct, fails) sorted by date."""
    tmp = defaultdict(lambda: defaultdict(lambda: dict(got=0.0, mx=0.0, date="", subj=[])))
    for r in exams:
        if not in_year(r.get("date"), ay):
            continue
        g = tmp[str(r.get("sid"))][(r.get("exam"), (r.get("date") or "")[:7])]
        g["date"] = max(g["date"], r.get("date") or "")
        if r.get("attended") != "Absent":
            g["got"] += num(r.get("marks"))
            g["mx"] += num(r.get("max"))
            g["subj"].append((r.get("subject", ""), num(r.get("marks")), num(r.get("max"))))
    out = {}
    for sid, groups in tmp.items():
        out[sid] = sorted(((g["date"], k[0], pct(g["got"], g["mx"]), g["subj"]) for k, g in groups.items()), key=lambda x: x[0])
    return out


def att_overall(att_month, sid, ay):
    pr = wk = 0
    for mth, (p, w) in att_month.get(sid, {}).items():
        if in_year(mth + "-01", ay):
            pr, wk = pr + p, wk + w
    return round(pr / wk * 100) if wk else None


def attention(students, exams, att_month, ay, pass_mark, att_alert, drop_alert):
    groups = exam_groups(exams, ay)
    out = []
    for s in students:
        sid, why = str(s["id"]), []
        g = groups.get(sid, [])
        last_pct = g[-1][2] if g else None
        if g:
            fails = [n for n, got, mx in g[-1][3] if mx and got / mx * 100 < pass_mark]
            if fails:
                why.append(f"Below pass mark in {', '.join(fails)} ({g[-1][1]})")
            if len(g) > 1 and g[-2][2] is not None and last_pct is not None and g[-2][2] - last_pct >= drop_alert:
                why.append(f"Marks fell {round(g[-2][2] - last_pct)} points ({g[-2][1]} {g[-2][2]}% to {g[-1][1]} {last_pct}%)")
        ap = att_overall(att_month, sid, ay)
        if ap is not None and ap < att_alert:
            why.append(f"Attendance only {ap}%")
        if why:
            out.append(dict(sid=sid, name=s.get("name"), cls=s.get("cls"), roll=s.get("roll"), phone=s.get("phone"),
                            why=why, last_pct=last_pct, att=ap))
    out.sort(key=lambda d: (-len(d["why"]), d["cls"] or "", d["name"] or ""))
    return out


def subject_matrix(exams, ay, class_order):
    cell, sub_all, trend = defaultdict(list), defaultdict(list), defaultdict(lambda: defaultdict(list))
    for r in exams:
        if not in_year(r.get("date"), ay) or r.get("attended") == "Absent" or not num(r.get("max")):
            continue
        p = num(r.get("marks")) / num(r.get("max")) * 100
        cell[(r.get("cls"), r.get("subject"))].append(p)
        sub_all[r.get("subject")].append(p)
        trend[r.get("subject")][r.get("exam")].append(p)
    subjects = sorted(sub_all, key=lambda s: -sum(sub_all[s]) / len(sub_all[s]))
    classes = [c for c in class_order if any(k[0] == c for k in cell)]
    avg = lambda l: round(sum(l) / len(l), 1) if l else None
    return dict(subjects=subjects, classes=classes, cell={k: avg(v) for k, v in cell.items()},
                overall=[(s, avg(sub_all[s]), len(sub_all[s])) for s in subjects],
                trend={s: {e: avg(v) for e, v in t.items()} for s, t in trend.items()})


def monthly_by_class(students, att_month, ay, class_order):
    cls_of = {str(s["id"]): s.get("cls") for s in students}
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    per = {}
    for sid, months in att_month.items():
        c = cls_of.get(sid)
        for mth, (p, w) in months.items():
            if not in_year(mth + "-01", ay):
                continue
            agg[c][mth][0] += p
            agg[c][mth][1] += w
    months = sorted({m for c in agg.values() for m in c})
    rows = [dict(cls=c, cells={m: (round(agg[c][m][0] / agg[c][m][1] * 100) if agg[c][m][1] else None) for m in months},
                 overall=round(sum(v[0] for v in agg[c].values()) / max(1, sum(v[1] for v in agg[c].values())) * 100))
            for c in class_order if c in agg]
    return months, rows


def fee_analysis(fees, students, ay):
    cls_of = {(s.get("name") or "").strip().lower(): s.get("cls") for s in students}
    by_month, by_class, per = defaultdict(float), defaultdict(lambda: [0.0, 0.0]), {}
    for f in fees:
        d = f.get("date") or ""
        if not in_year(d, ay):
            continue
        nm = (f.get("student") or "").strip().lower()
        c = f.get("cls") or cls_of.get(nm) or "-"
        due, paid = num(f.get("due")), num(f.get("paid"))
        by_month[d[:7]] += paid
        by_class[c][0] += due
        by_class[c][1] += paid
        p = per.setdefault(nm, dict(name=f.get("student"), cls=c, due=0.0, paid=0.0, oldest=d))
        p["due"] += due
        p["paid"] += paid
        if d and (not p["oldest"] or d < p["oldest"]):
            p["oldest"] = d
    pending = sorted((dict(p, bal=p["due"] - p["paid"]) for p in per.values() if p["due"] - p["paid"] > 0), key=lambda p: p["oldest"] or "9")
    tot_due, tot_paid = sum(v[0] for v in by_class.values()), sum(v[1] for v in by_class.values())
    return dict(by_month=sorted(by_month.items()), by_class=by_class, pending=pending, due=tot_due, paid=tot_paid)


def admissions_analysis(adm, ay):
    rows = [a for a in adm if in_year(a.get("date"), ay)]
    st, mo, src, cl = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    for a in rows:
        st[a.get("status") or "Applied"] += 1
        mo[(a.get("date") or "")[:7]] += 1
        src[a.get("source") or "Not recorded"] += 1
        cl[a.get("cls") or "-"] += 1
    n = len(rows)
    return dict(n=n, status=st, months=sorted(mo.items()), source=src, classes=cl,
                conv=round(st.get("Admitted", 0) / n * 100) if n else None)


def competitive_analysis(comp, ay):
    mx, order = defaultdict(lambda: defaultdict(int)), ["Registered", "Attended", "Result awaited", "Qualified", "Not qualified"]
    for c in comp:
        if in_year(c.get("date"), ay):
            mx[c.get("exam") or "Other"][c.get("status") or "Registered"] += 1
    return dict(matrix=mx, statuses=order)


def heat(v):
    return "" if v is None else f"background:hsl({round(max(0, min(100, v)) * 1.2)},70%,86%)"
