from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sys
from pathlib import Path
from typing import Any

import itasca

from capture_store import (
    atomic_write_json,
    canonical_json,
    initialize_raw_spools,
    initialize_run_dirs,
    read_json,
    sha256_bytes,
    sha256_file,
    utc_now,
)


FISH_PREFIX = "pfclc_gui_v4"
CYCLE_CALLBACK = f"_{FISH_PREFIX}_cycle"
SOLVE_START_CALLBACK = f"_{FISH_PREFIX}_solve_start"
SOLVE_COMPLETE_CALLBACK = f"_{FISH_PREFIX}_solve_complete"
BOND_CALLBACK = f"_{FISH_PREFIX}_bond"
CALLBACK_POSITION = 49.5


def vec(value: Any) -> list[float]:
    result = [float(item) for item in list(value)]
    if len(result) != 3 or not all(math.isfinite(item) for item in result):
        raise RuntimeError(f"Invalid 3-vector from PFC: {value!r}")
    return result


def snapshot() -> dict[str, Any]:
    return {
        "pid": int(os.getpid()),
        "cwd": str(Path.cwd()),
        "executable": sys.executable,
        "python": platform.python_version(),
        "cycle": int(itasca.cycle()),
        "mechanical_time_total": float(itasca.mech_age()),
        "balls": int(itasca.ball.count()),
        "walls": int(itasca.wall.count()),
        "wall_vertices": int(itasca.wall.vertex.count()),
        "wall_facets": int(itasca.wall.facet.count()),
        "contacts": int(itasca.contact.count()),
        "fractures": int(itasca.dfn.fracture.count()),
    }


def read_static() -> dict[str, Any]:
    balls = []
    for ball in itasca.ball.list():
        position = vec(ball.pos())
        balls.append(
            {
                "id": int(ball.id()),
                "x": position[0],
                "y": position[1],
                "z": position[2],
                "radius": float(ball.radius()),
            }
        )
    balls.sort(key=lambda row: row["id"])
    walls = []
    for wall in itasca.wall.list():
        vertices = [
            {
                "id": int(vertex.id()),
                "position": vec(vertex.pos()),
            }
            for vertex in wall.vertices()
        ]
        vertices.sort(key=lambda row: row["id"])
        facets = [
            {
                "id": int(facet.id()),
                "active": int(facet.active()),
                "normal": vec(facet.normal()),
                "position": vec(facet.pos()),
            }
            for facet in wall.facets()
        ]
        facets.sort(key=lambda row: row["id"])
        walls.append(
            {
                "id": int(wall.id()),
                "name": str(wall.name()),
                "position": vec(wall.pos()),
                "displacement": vec(wall.disp()),
                "velocity": vec(wall.vel()),
                "spin": vec(wall.spin()),
                "euler": vec(wall.euler()),
                "rotation_center": vec(wall.rotation_center()),
                "force_contact": vec(wall.force_contact()),
                "vertices": vertices,
                "facets": facets,
            }
        )
    walls.sort(key=lambda row: row["id"])
    return {"balls": balls, "walls": walls}


def model_identity(static: dict[str, Any]) -> dict[str, Any]:
    topology = {
        "balls": [
            {
                "id": row["id"],
                "radius": row["radius"],
                "x": row["x"],
                "y": row["y"],
                "z": row["z"],
            }
            for row in static["balls"]
        ],
        "walls": [
            {
                "id": row["id"],
                "name": row["name"],
                "vertices": [
                    {
                        "id": vertex["id"],
                        "position": vertex["position"],
                    }
                    for vertex in row["vertices"]
                ],
                "facets": [
                    {
                        "id": facet["id"],
                        "normal": facet["normal"],
                    }
                    for facet in row["facets"]
                ],
            }
            for row in static["walls"]
        ],
    }
    digest = sha256_bytes(canonical_json(topology))
    return {
        "sha256": digest,
        "ball_count": len(static["balls"]),
        "wall_count": len(static["walls"]),
        "wall_vertex_count": sum(
            len(row["vertices"]) for row in static["walls"]
        ),
        "topology": topology,
    }


def fish_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "\\'")


def write_static_bundle(
    run_dir: Path,
    *,
    run_id: str,
    config: dict[str, Any],
    static: dict[str, Any],
    identity: dict[str, Any],
    snap: dict[str, Any],
) -> dict[str, Any]:
    static_dir = run_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(static_dir / "balls.json", static["balls"])
    atomic_write_json(static_dir / "walls.json", static["walls"])
    baseline_fractures = []
    for fracture in itasca.dfn.fracture.list():
        baseline_fractures.append(
            {
                "id": int(fracture.id()),
                "dfn_name": str(fracture.dfn().name()),
                "position": vec(fracture.pos()),
                "normal": vec(fracture.normal()),
                "diameter": float(fracture.diameter()),
            }
        )
    baseline_fractures.sort(key=lambda row: row["id"])
    atomic_write_json(
        static_dir / "model.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "pid": snap["pid"],
            "snapshot": snap,
            "model_identity": identity,
            "balls": static["balls"],
            "walls": static["walls"],
            "baseline_fractures": baseline_fractures,
        },
    )
    history_rows = []
    for name in config.get("history_names", ["1", "2", "3"]):
        try:
            array = itasca.history.get(str(name))
        except Exception:
            continue
        history_rows.append(
            {
                "name": str(name),
                "shape": [int(value) for value in array.shape],
                "source": "itasca.history.get() in GUI process at arm time",
            }
        )
    atomic_write_json(
        static_dir / "histories.json",
        {
            "histories": history_rows,
            "note": (
                "Native histories are copied at finalization. Frame stress, "
                "strain, load and displacement are derived only from the raw "
                "Wall position/displacement/contact force fields in the same frame."
            ),
        },
    )
    files = []
    for name in ("balls.json", "walls.json", "model.json", "histories.json"):
        path = static_dir / name
        files.append(
            {
                "path": name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    bundle_hash = sha256_bytes(canonical_json(files))
    manifest = {
        "run_id": run_id,
        "pid": snap["pid"],
        "generated_utc": utc_now(),
        "files": files,
        "bundle_sha256": bundle_hash,
        "capture_config": config,
    }
    atomic_write_json(static_dir / "manifest.json", manifest)
    return manifest


def fish_source(run_dir: Path, sample_mode: str, sample_value: float) -> str:
    raw = run_dir / "recovery" / "raw"
    return f"""
fish define _{FISH_PREFIX}_init
  global _{FISH_PREFIX}_enabled = false
  global _{FISH_PREFIX}_frame_id = 0
  global _{FISH_PREFIX}_last_cycle = -1
  global _{FISH_PREFIX}_last_time = -1.0
  global _{FISH_PREFIX}_calls = 0
  global _{FISH_PREFIX}_events = 0
  global _{FISH_PREFIX}_solve_sequence = 0
  global _{FISH_PREFIX}_solve_event_id = 0
  global _{FISH_PREFIX}_sample_mode = '{sample_mode}'
  global _{FISH_PREFIX}_sample_value = {float(sample_value)}
  global _{FISH_PREFIX}_run_id = ''
  global _{FISH_PREFIX}_ball_path = '{fish_path(raw / "ball_spool.csv")}'
  global _{FISH_PREFIX}_wall_path = '{fish_path(raw / "wall_spool.csv")}'
  global _{FISH_PREFIX}_vertex_path = '{fish_path(raw / "wall_vertex_spool.csv")}'
  global _{FISH_PREFIX}_frame_path = '{fish_path(raw / "frame_spool.csv")}'
  global _{FISH_PREFIX}_event_path = '{fish_path(raw / "bond_spool.csv")}'
  global _{FISH_PREFIX}_solve_path = '{fish_path(raw / "solve_spool.csv")}'
end

fish define _{FISH_PREFIX}_append_solve(ev,msg)
  _{FISH_PREFIX}_solve_event_id = _{FISH_PREFIX}_solve_event_id + 1
  local event_id = _{FISH_PREFIX}_solve_event_id
  local row = string.build('%1,%2,%3,%4,%5,%6',event_id,ev,_{FISH_PREFIX}_solve_sequence,mech.cycle(),mech.time.total(),msg)
  local rows = list()
  rows = list.append(rows,row)
  local handle = file.open(_{FISH_PREFIX}_solve_path,'append','text')
  file.write(handle,rows)
  file.close(handle)
end

fish define _{FISH_PREFIX}_in_interval
  if _{FISH_PREFIX}_sample_mode = 'cycle' then
    if (mech.cycle() - _{FISH_PREFIX}_last_cycle) >= _{FISH_PREFIX}_sample_value then
      _{FISH_PREFIX}_in_interval = true
    else
      _{FISH_PREFIX}_in_interval = false
    endif
  else
    if (mech.time.total() - _{FISH_PREFIX}_last_time) >= _{FISH_PREFIX}_sample_value then
      _{FISH_PREFIX}_in_interval = true
    else
      _{FISH_PREFIX}_in_interval = false
    endif
  endif
end

fish define _{FISH_PREFIX}_sample(role)
  local started = time.clock()
  local c0 = mech.cycle()
  local t0 = mech.time.total()
  local b0 = ball.num()
  local w0 = wall.num()
  local v0 = wall.vertex.num()
  local fid = _{FISH_PREFIX}_frame_id + 1
  local identity_ok = 1
  local identity_reason = 'OK'

  local bws = time.clock()
  local ball_rows = list()
  loop foreach local b ball.list
    local bp = ball.pos(b)
    ball_rows = list.append(ball_rows,string.build('%1,%2,%3,%4,%5,%6', ...
      fid,ball.id(b),comp.x(bp),comp.y(bp),comp.z(bp),ball.radius(b)))
  endloop
  local bh = file.open(_{FISH_PREFIX}_ball_path,'append','text')
  file.write(bh,ball_rows)
  file.close(bh)

  local wall_rows = list()
  local vertex_rows = list()
  loop foreach local w wall.list
    local wp = wall.pos(w)
    local wd = wall.disp(w)
    local wv = wall.vel(w)
    local ws = wall.spin(w)
    local we = wall.euler(w)
    local wf = wall.force.contact(w)
    local wc = wall.vertex.num()
    local wall_row = string.build('%1,%2,%3,%4,%5,%6,%7,%8,%9', ...
      fid,wall.id(w),comp.x(wp),comp.y(wp),comp.z(wp), ...
      comp.x(wd),comp.y(wd),comp.z(wd),comp.x(wv)) + ',' + ...
      string.build('%1,%2,%3,%4,%5,%6,%7,%8,%9', ...
      comp.y(wv),comp.z(wv),comp.x(ws),comp.y(ws),comp.z(ws), ...
      comp.x(we),comp.y(we),comp.z(we),comp.x(wf)) + ',' + ...
      string.build('%1,%2,%3',comp.y(wf),comp.z(wf),wc)
    wall_rows = list.append(wall_rows,wall_row)
  endloop
  loop foreach local vertex wall.vertex.list()
    local vp = wall.vertex.pos(vertex)
    vertex_rows = list.append(vertex_rows,string.build('%1,%2,%3,%4,%5', ...
      fid,wall.vertex.id(vertex),comp.x(vp),comp.y(vp),comp.z(vp)))
  endloop
  local wh = file.open(_{FISH_PREFIX}_wall_path,'append','text')
  file.write(wh,wall_rows)
  file.close(wh)
  local vh = file.open(_{FISH_PREFIX}_vertex_path,'append','text')
  file.write(vh,vertex_rows)
  file.close(vh)
  local write_ms = (time.clock() - bws) * 10.0

  local c1 = mech.cycle()
  local t1 = mech.time.total()
  local b1 = ball.num()
  local w1 = wall.num()
  local v1 = wall.vertex.num()
  if c0 # c1 then
    identity_ok = 0
    identity_reason = 'CYCLE_CHANGED_DURING_READ'
  endif
  if t0 # t1 then
    identity_ok = 0
    identity_reason = 'TIME_CHANGED_DURING_READ'
  endif
  if b0 # b1 then
    identity_ok = 0
    identity_reason = 'BALL_COUNT_CHANGED_DURING_READ'
  endif
  if w0 # w1 then
    identity_ok = 0
    identity_reason = 'WALL_COUNT_CHANGED_DURING_READ'
  endif
  if v0 # v1 then
    identity_ok = 0
    identity_reason = 'VERTEX_COUNT_CHANGED_DURING_READ'
  endif
  if identity_ok = 0 then
    _{FISH_PREFIX}_events = _{FISH_PREFIX}_events + 1
  endif

  local capture_ms = (time.clock() - started) * 10.0
  local frame_row = string.build('%1,%2,%3,%4,%5,%6,%7,%8,%9', ...
    fid,c0,t0,b0,w0,v0,capture_ms,write_ms,_{FISH_PREFIX}_calls) + ',' + ...
    string.build('%1,%2',identity_ok,identity_reason) + ',' + role
  local frame_rows = list()
  frame_rows = list.append(frame_rows,frame_row)
  local fh = file.open(_{FISH_PREFIX}_frame_path,'append','text')
  file.write(fh,frame_rows)
  file.close(fh)

  _{FISH_PREFIX}_frame_id = fid
  _{FISH_PREFIX}_last_cycle = c0
  _{FISH_PREFIX}_last_time = t0
end

fish define _{FISH_PREFIX}_cycle
  _{FISH_PREFIX}_calls = _{FISH_PREFIX}_calls + 1
  if _{FISH_PREFIX}_enabled = false then
    exit
  endif
  _{FISH_PREFIX}_in_interval
  if _{FISH_PREFIX}_in_interval = true then
    _{FISH_PREFIX}_sample('INTERVAL')
  endif
end

fish define _{FISH_PREFIX}_solve_start
  _{FISH_PREFIX}_enabled = true
  _{FISH_PREFIX}_solve_sequence = _{FISH_PREFIX}_solve_sequence + 1
  _{FISH_PREFIX}_append_solve('SOLVE_START','')
  if mech.cycle() > _{FISH_PREFIX}_last_cycle then
    _{FISH_PREFIX}_sample('START')
  endif
end

fish define _{FISH_PREFIX}_solve_complete(msg)
  if _{FISH_PREFIX}_enabled = true then
    if mech.cycle() > _{FISH_PREFIX}_last_cycle then
      _{FISH_PREFIX}_sample('FINAL')
    endif
    if string.len(msg) = 0 then
      _{FISH_PREFIX}_append_solve('SOLVE_COMPLETE','OK')
    else
      _{FISH_PREFIX}_append_solve('SOLVE_COMPLETE','ERROR_PRESENT')
    endif
  endif
  _{FISH_PREFIX}_enabled = false
end

fish define _{FISH_PREFIX}_endpoint_ball_id(piece)
  if type.pointer(piece) = 'ball' then
    _{FISH_PREFIX}_endpoint_ball_id = ball.id(piece)
  else
    _{FISH_PREFIX}_endpoint_ball_id = -1
  endif
end

fish define _{FISH_PREFIX}_bond(entries)
  if _{FISH_PREFIX}_enabled = false then
    exit
  endif
  local contact = entries(1)
  local p = contact.pos(contact)
  local n = contact.normal(contact)
  local size = contact.prop(contact,'pb_radius')
  local endpoint1 = contact.end1(contact)
  local endpoint2 = contact.end2(contact)
  local ball_a = _{FISH_PREFIX}_endpoint_ball_id(endpoint1)
  local ball_b = _{FISH_PREFIX}_endpoint_ball_id(endpoint2)
  _{FISH_PREFIX}_events = _{FISH_PREFIX}_events + 1
  local row = string.build('%1,%2,%3,%4,%5,%6,%7,%8,%9,%10,%11', ...
    _{FISH_PREFIX}_events,mech.cycle(),mech.time.total(),contact.id(contact), ...
    ball_a,ball_b,entries(2),entries(3),comp.x(p),comp.y(p),comp.z(p)) + ',' + ...
    string.build('%1,%2,%3,%4',comp.x(n),comp.y(n),comp.z(n),size)
  local rows = list()
  rows = list.append(rows,row)
  local handle = file.open(_{FISH_PREFIX}_event_path,'append','text')
  file.write(handle,rows)
  file.close(handle)
end
"""


def install_fish(run_dir: Path, config: dict[str, Any]) -> None:
    sample_mode = str(config.get("sample_mode", "cycle"))
    if sample_mode not in {"cycle", "time"}:
        raise ValueError(f"Unsupported sample_mode: {sample_mode}")
    sample_value = float(
        config.get("sample_value", 1000 if sample_mode == "cycle" else 0.5)
    )
    if sample_value <= 0:
        raise ValueError("sample_value must be positive")
    init_function = f"_{FISH_PREFIX}_init"
    if not itasca.fish.has(init_function):
        itasca.command(fish_source(run_dir, sample_mode, sample_value))
    itasca.fish.call_function(init_function)
    for name, event in (
        (SOLVE_START_CALLBACK, "solve_start"),
        (SOLVE_COMPLETE_CALLBACK, "solve_complete"),
        (BOND_CALLBACK, "bond_break"),
    ):
        try:
            itasca.command(f"fish callback remove {name} event {event}")
        except Exception:
            pass
        try:
            itasca.command(f"fish callback add {name} event {event}")
        except Exception as exc:
            if "already registered" not in str(exc):
                raise
    try:
        itasca.command(
            f"fish callback remove {CYCLE_CALLBACK} {CALLBACK_POSITION}"
        )
    except Exception:
        pass
    try:
        itasca.command(
            f"fish callback add {CYCLE_CALLBACK} {CALLBACK_POSITION}"
        )
    except Exception as exc:
        if "already registered" not in str(exc):
            raise
    itasca.fish.set(f"_{FISH_PREFIX}_run_id", str(config["run_id"]))
    raw = run_dir / "recovery" / "raw"
    itasca.fish.set(
        f"_{FISH_PREFIX}_sample_mode", sample_mode
    )
    itasca.fish.set(
        f"_{FISH_PREFIX}_sample_value", sample_value
    )
    itasca.fish.set(
        f"_{FISH_PREFIX}_ball_path", fish_path(raw / "ball_spool.csv")
    )
    itasca.fish.set(
        f"_{FISH_PREFIX}_wall_path", fish_path(raw / "wall_spool.csv")
    )
    itasca.fish.set(
        f"_{FISH_PREFIX}_vertex_path",
        fish_path(raw / "wall_vertex_spool.csv"),
    )
    itasca.fish.set(
        f"_{FISH_PREFIX}_frame_path", fish_path(raw / "frame_spool.csv")
    )
    itasca.fish.set(
        f"_{FISH_PREFIX}_event_path", fish_path(raw / "bond_spool.csv")
    )
    itasca.fish.set(
        f"_{FISH_PREFIX}_solve_path", fish_path(raw / "solve_spool.csv")
    )
    itasca.fish.set(f"_{FISH_PREFIX}_frame_id", 0)
    itasca.fish.set(f"_{FISH_PREFIX}_last_cycle", -1)
    itasca.fish.set(f"_{FISH_PREFIX}_last_time", -1.0)
    itasca.fish.set(f"_{FISH_PREFIX}_calls", 0)
    itasca.fish.set(f"_{FISH_PREFIX}_events", 0)
    itasca.fish.set(f"_{FISH_PREFIX}_solve_sequence", 0)
    itasca.fish.set(f"_{FISH_PREFIX}_solve_event_id", 0)
    itasca.fish.set(f"_{FISH_PREFIX}_enabled", False)


def main() -> int:
    config_path = Path(
        os.environ.get("PFC_LIVE_CAPTURE_CONFIG", "")
    ).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(
            "PFC_LIVE_CAPTURE_CONFIG must point to an arm config JSON"
        )
    config = read_json(config_path)
    run_dir = Path(config["run_dir"]).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    initialize_run_dirs(run_dir)
    initialize_raw_spools(run_dir)
    snap = snapshot()
    if snap["balls"] <= 0:
        raise RuntimeError("Model has no Balls; refusing to arm capture")
    static = read_static()
    identity = model_identity(static)
    if int(config.get("expected_pid", snap["pid"])) != snap["pid"]:
        raise RuntimeError(
            f"PID mismatch: {snap['pid']} != {config['expected_pid']}"
        )
    static_manifest = write_static_bundle(
        run_dir,
        run_id=str(config["run_id"]),
        config=config,
        static=static,
        identity=identity,
        snap=snap,
    )
    install_fish(run_dir, config)
    arm_result = {
        "status": "ARMED",
        "run_id": str(config["run_id"]),
        "pid": snap["pid"],
        "snapshot": snap,
        "model_identity": {
            "sha256": identity["sha256"],
            "ball_count": identity["ball_count"],
            "wall_count": identity["wall_count"],
            "wall_vertex_count": identity["wall_vertex_count"],
        },
        "static_bundle_sha256": static_manifest["bundle_sha256"],
        "sample_mode": str(config.get("sample_mode", "cycle")),
        "sample_value": float(
            config.get(
                "sample_value",
                1000 if config.get("sample_mode", "cycle") == "cycle" else 0.5,
            )
        ),
        "cycle_callback": CYCLE_CALLBACK,
        "cycle_callback_position": CALLBACK_POSITION,
        "event_callbacks": [
            "solve_start",
            "solve_ending",
            "solve_complete",
            "bond_break",
        ],
        "armed_utc": utc_now(),
    }
    atomic_write_json(run_dir / "metadata" / "arm_result.json", arm_result)
    atomic_write_json(run_dir / "metadata" / "arm_config.json", config)
    print(json.dumps(arm_result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    _result = main()
    if _result:
        raise RuntimeError(f"arm_capture failed with status {_result}")

