"""Clinic evening simulator v2. Minute-step. Policy is a dict of knobs so each
iteration can change one thing. Times: minutes after official start (0 = 7:00pm)."""
import random, math, statistics as st, json, sys

def lognorm(median, spread):
    return max(3, random.lognormvariate(math.log(median), spread))

def world(seed, scenario):
    r = random.Random(seed)
    random.seed(seed)
    N = scenario.get("N", 30)
    w = dict(
        _=0,
        N=N,
        doctor_says=12, doc_travel=r.uniform(*scenario.get("doc_travel",[30,30])),                                   # what doctor typed at setup
        true_pace=r.choice(scenario.get("paces", [8, 12, 16])),
        doctor_start=r.choice(scenario.get("lates", [0, 15, 30, 45, 70])),
        late_warned=r.random() < scenario.get("p_warn", 0.0),  # doctor taps "I'll arrive at X"
        noshow=[r.random() < scenario.get("p_noshow", 0.15) for _ in range(N)],
        travel=[r.uniform(10, 50) for _ in range(N)],
        traffic=[r.uniform(0.8, 1.6) for _ in range(N)],   # true / map estimate
        slow_leave=[r.random() < 0.2 for _ in range(N)],     # patient leaves 10-20 min after told
        tap_lag=scenario.get("tap_lag", 0),
    )
    if scenario.get("carry"): w["doctor_says"] = w["true_pace"] * r.uniform(0.9, 1.1)  # learned from past evenings
    if scenario.get("carry") == "mean":   # learned AVERAGE visit (lognormal mean + long cases), as Tarek will learn it
        avg = w["true_pace"] * math.exp(scenario.get("spread", 0.5) ** 2 / 2) + scenario.get("long_cases", 3) * 22.5 / N
        w["doctor_says"] = avg * r.uniform(0.9, 1.1)
    w["visits"] = [lognorm(w["true_pace"], scenario.get("spread",0.5)) for _ in range(N)]
    for i in r.sample(range(N), scenario.get("long_cases",3)):
        w["visits"][i] += r.uniform(15, 30)
    w["slow_by"] = [r.uniform(10, 20) for _ in range(N)]
    w["map"] = [w["travel"][i] / w["traffic"][i] for i in range(N)]
    if scenario.get("booking"):
        book_windows(w, r, scenario)
    return w

def book_windows(w, r, sc):
    """Booking method test (2026-09-26). Patients book in index order.
    earliest = a real life limit ("can't come before 8"), unknown to the system in 'day' mode.
    day: queue number = booking order; a limited patient just arrives late.
    ordered: Tarek offers the earliest window with space; patient refuses windows before their limit.
    free: patient picks their preferred window (random), nearest with space if full."""
    N = w["N"]; W = sc.get("win_len", 60)
    rnd = {"round": round, "ceil": math.ceil, "floor": math.floor}[sc.get("places", "round")]
    cap = max(1, rnd(W / w["doctor_says"]))             # places per window from the learned pace
    nwin = -(-sc.get("cap", 30) // cap)                  # enough windows to hold the doctor's daily cap
    earliest = [r.choice([60, 120, 180]) if r.random() < sc.get("p_limit", 0.3) else 0 for _ in range(N)]
    pref = [r.randrange(nwin) for _ in range(N)]
    mode = sc["booking"]
    win = [None] * N; used = [0] * nwin; conflict = 0
    for p in range(N):
        ok = [k for k in range(nwin) if used[k] < cap and k * W >= earliest[p]]
        if mode == "day":
            continue
        if not ok:
            ok = [k for k in range(nwin) if used[k] < cap]; conflict += 1
        if mode == "ordered":
            k = ok[0]
        else:
            want = max(pref[p], earliest[p] // W)
            k = min(ok, key=lambda k: (abs(k - want), k))
        win[p] = k; used[k] += 1
    if mode == "day":
        w["order"] = list(range(N))
        w["floor"] = earliest
        conflict = sum(1 for i, p in enumerate(w["order"]) if i * w["doctor_says"] < earliest[p])
        w["win_start"] = [0] * N
    else:
        w["order"] = sorted(range(N), key=lambda p: (win[p], p))
        w["win_start"] = [win[p] * W for p in range(N)]
        pull = sc.get("early_pull", 0)                   # patient told "we may call you up to X min before your window"
        w["floor"] = [max(w["win_start"][p] - pull, earliest[p]) for p in range(N)]
        w["win_len"] = W
    w["conflict"] = conflict

def run(P, seed, scenario, trace=False):
    w = world(seed, scenario)
    N = w["N"]
    est = w["doctor_says"]; hist = []
    shown = [i * est for i in range(N)]           # "expected around" shown at booking
    if "order" in w:
        for i, p in enumerate(w["order"]): shown[p] = max(i * est, w["win_start"][p])
    changes = [0] * N
    uncertain = [False] * N; long_tap = [False] * N; proj_told = [None] * N; told = [None] * N; silent = [None] * N; arrive = [None] * N; seen = [None] * N
    absent_since = [None] * N; late_rejoin = [False] * N
    doctor_in = False; busy_until = None; current = None
    idle = 0; log = []
    known_start = w["doctor_start"] if w["late_warned"] else 0
    t = -60
    order = list(w.get("order", range(N)))          # queue order (can be reshuffled for late arrivals)
    while t < 900:
        # doctor arrival
        if not doctor_in and t >= w["doctor_start"]:
            doctor_in = True
            if trace: log.append((t, "DOCTOR", "arrives, taps start"))
        # system's belief of when the doctor becomes free
        if doctor_in:
            if current is not None and busy_until and busy_until > t:
                extra = 20 if (P.get("long_btn") and long_tap[current] and t >= seen[current] + 5) else 0
                free_at = max(t + 1, seen[current] + est + extra)
            else:
                free_at = t
        else:
            if P.get("on_my_way"):
                tap_at = w["doctor_start"] - w["doc_travel"]   # he taps when he actually leaves
                free_at = max(t, tap_at + 30) if t >= tap_at else max(t + 30, 0)   # system assumes learned 30 min
            else:
                free_at = max(t, known_start)
        # remaining queue (skip patients marked absent)
        remaining = [p for p in order if seen[p] is None and absent_since[p] is None]
        # projected start per patient
        proj = {}; k = 0
        for p in remaining:
            proj[p] = free_at + k * est
            if not (uncertain[p] and not (arrive[p] is not None and arrive[p] <= t)): k += 1
        # patient-facing time updates
        for p in remaining:
            new = proj[p]
            if P["display"] == "live":
                if abs(new - shown[p]) >= 5: shown[p] = new; changes[p] += 1
            else:
                drift = new - shown[p]
                allow_earlier = P.get("allow_earlier", False)
                if told[p] is None and (drift >= P["update_min"] or (allow_earlier and drift <= -P["update_min"])):
                    shown[p] = new; changes[p] += 1
                    if trace and p == P.get("watch"): log.append((t, f"P{p}", f"time updated to {fmt(new)}"))
        # leave-home trigger
        gate = P.get("gate_on_tap") and P.get("on_my_way") and not doctor_in and t < w["doctor_start"] - w["doc_travel"]   # 2026-09-28: nobody told to leave before the doctor taps
        for k, p in enumerate(remaining):
            if told[p] is not None or gate: continue
            ahead_cushion = P["cushion_min"] if P.get("cushion_min") is not None else P["cushion"] * est   # 2026-09-28: cushion in minutes (the doctor's dial)
            padded = w["map"][p] * P["traffic_mult"] + P["buffer"]
            trigger = proj[p] - ahead_cushion - padded <= t
            if P.get("min_ahead") is not None and k <= P["min_ahead"]: trigger = True
            if P.get("baseline") == "all_at_7": trigger = t >= -w["travel"][p]
            elif P.get("baseline") == "slots": trigger = t >= p * w["doctor_says"] - w["travel"][p]
            if trigger:
                told[p] = t; proj_told[p] = proj[p]
                if not w["noshow"][p]:
                    lag = w["slow_by"][p] if w["slow_leave"][p] else 0
                    arrive[p] = t + lag + w["travel"][p]
                    if "floor" in w: arrive[p] = max(arrive[p], w["floor"][p])   # can't / won't come before window or life limit
                if P.get("p_reply") is not None:
                    replies = (not w["noshow"][p]) and random.random() < P["p_reply"]
                    if not replies: silent[p] = t
                if trace and p == P.get("watch"): log.append((t, f"P{p}", "gets LEAVE NOW"))
        for p in range(N):  # no 'on my way' within 10 min -> treat as absent, pull the next patient
            if silent[p] is not None and t - silent[p] == 10 and seen[p] is None and absent_since[p] is None and not (arrive[p] is not None and arrive[p] <= t):
                if P.get("silent_mode") == "bump": absent_since[p] = t
                else: uncertain[p] = True
        # doctor calls next
        if doctor_in and (busy_until is None or t >= busy_until):
            if current is not None:
                current = None
            present = [p for p in [q for q in order if seen[q] is None] if arrive[p] is not None and arrive[p] <= t]
            # mark absent: called-turn patients not present
            if remaining and remaining[0] not in present and told[remaining[0]] is not None and t - max(told[remaining[0]], 0) > w["map"][remaining[0]] * P["traffic_mult"] + P["buffer"] + P["grace"]:
                absent_since[remaining[0]] = t
            if present:
                p = present[0]
                seen[p] = t; current = p
                busy_until = t + w["visits"][p]
                long_tap[p] = w["visits"][p] > 25 and random.random() < 0.7
                # learning from doctor taps (tap may lag)
                if P["learn"]:
                    pass
                if trace and (p == P.get("watch")): log.append((t, f"P{p}", "called in"))
            else:
                if any(seen[q] is None and not w["noshow"][q] for q in range(N)):
                    idle += 1
        # when a visit ends, record duration (with tap lag noise)
        if current is not None and busy_until is not None and t + 1 >= busy_until:
            dur = w["visits"][current] + w["tap_lag"] * random.random()
            hist.append(dur)
            if P["learn"] == "mean":
                est = st.mean(hist[-10:]) if len(hist) >= 3 else (w["doctor_says"] * 2 + sum(hist)) / (2 + len(hist))
            if P["learn"] == "median":
                est = st.median(hist[-8:]) if len(hist) >= 3 else (w["doctor_says"] * 2 + sum(hist)) / (2 + len(hist))
        # absent patients who show up later rejoin after next 2
        for p in range(N):
            if absent_since[p] is not None and arrive[p] is not None and arrive[p] <= t and seen[p] is None:
                absent_since[p] = None
                order.remove(p)
                rem = [q for q in order if seen[q] is None and absent_since[q] is None]
                pos_after = rem[min(P["late_after"], len(rem)) - 1] if rem else None
                idx = order.index(pos_after) + 1 if pos_after is not None else len(order)
                order.insert(idx, p); late_rejoin[p] = True
        if all(seen[p] is not None or w["noshow"][p] for p in range(N)) and doctor_in and (busy_until is None or t >= busy_until):
            break
        t += 1
    S = [p for p in range(N) if seen[p] is not None]
    waits = [seen[p] - arrive[p] for p in S]
    promise_miss = [seen[p] - shown[p] for p in S]   # seen vs last time shown
    res = dict(
        changes_avg=st.mean(changes[p] for p in S), changes_max=max(changes[p] for p in S),
        wait_med=st.median(waits), wait_p90=sorted(waits)[int(.9 * len(waits))], wait_max=max(waits),
        over45=sum(w_ > 45 for w_ in waits),
        idle=idle, finish=t, seen=len(S), expected=N - sum(w["noshow"]),
        missed=sum(1 for p in range(N) if seen[p] is None and not w["noshow"][p]),
        slip=[seen[p]-proj_told[p] for p in S], early=[proj_told[p]-arrive[p] for p in S], late_rejoins=sum(late_rejoin), pace=w["true_pace"], late=w["doctor_start"],
        conflict=w.get("conflict", 0), last_seen=max(seen[p] for p in S),
        after_win=sum(1 for p in S if "win_len" in w and seen[p] > w["win_start"][p] + w["win_len"]),
        before_win=sum(1 for p in S if "win_len" in w and seen[p] < w["win_start"][p]),
        over_by=st.mean([seen[p] - w["win_start"][p] - w["win_len"] for p in S if "win_len" in w and seen[p] > w["win_start"][p] + w["win_len"]] or [0]))
    return (res, log) if trace else res

def fmt(m):
    m = int(round(m)); h = 7 + m // 60; return f"{h}:{m % 60:02d}pm"

def summary(P, scenario, n=300):
    rs = [run(P, s, scenario) for s in range(n)]
    f = lambda k: st.mean(r[k] for r in rs)
    for r in rs: r.pop('slip', None); r.pop('early', None)
    worst_idle = max(r["idle"] for r in rs)
    return dict(changes=round(f("changes_avg"), 1), changes_max=round(f("changes_max"), 1),
                wait_med=round(f("wait_med")), wait_p90=round(f("wait_p90")), wait_max=round(f("wait_max")),
                over45=round(f("over45"), 1), idle=round(f("idle")), idle_worst=worst_idle,
                missed=round(f("missed"), 2), rejoins=round(f("late_rejoins"), 1),
                conflict=round(f("conflict"), 1), last_seen=round(f("last_seen")),
                after_win=round(f("after_win"), 1), before_win=round(f("before_win"), 1), over_by=round(f("over_by")))

if __name__ == "__main__":
    P = json.loads(sys.argv[1]); scenario = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(summary(P, scenario)))
