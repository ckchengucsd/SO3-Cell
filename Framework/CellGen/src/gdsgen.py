from pprint import pprint
import pya
import sys
import re
import os, json
from pathlib import Path
sys.path.append('./src')
from gdsInfoClass import M0,M1,M2,V0,V1,V2,GATE,LISD,GCUT,ACTIVE,Nselect,Pselect,SDT,WELL,BPR,heal_m05_corners,heal_m04_tips,set_track_height,set_geometry_constants,ACT_BOTTOM_ANCHOR,LEGACY_ACT_CENTER_ANCHOR,set_cur_width,set_row_scheme,_m0_track_ybot

output_dir = "gds_result"
cells = None
mh_order = "N_FIRST"
port_nets_map = {}


def _require_int(mapping, key, where):
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"gdsgen.py: {where}.{key} must be an integer, got {value!r}")
    return value


def _validate_geometry_config(raw_geometry):
    if not isinstance(raw_geometry, dict):
        raise RuntimeError("gdsgen.py: GDSGEN_CONFIG.geometry must be a JSON object")
    if raw_geometry.get("schema_version") != 1:
        raise RuntimeError(
            "gdsgen.py: geometry.schema_version must be integer 1 "
            f"(got {raw_geometry.get('schema_version')!r})"
        )
    for key in (
        "track_count",
        "track_pitch_raw",
        "m0_power_rail_width_raw",
        "m0_power_rail_to_first_track_raw",
        "bpr_rail_width_raw",
        "act_bottom_anchor_raw",
        "legacy_act_center_anchor_raw",
    ):
        _require_int(raw_geometry, key, "geometry")
    if raw_geometry["track_count"] <= 0 or raw_geometry["track_pitch_raw"] <= 0:
        raise RuntimeError("gdsgen.py: geometry.track_count and geometry.track_pitch_raw must be positive")
    sdcon = raw_geometry.get("sdcon")
    if not isinstance(sdcon, dict):
        raise RuntimeError("gdsgen.py: geometry.sdcon must be a JSON object")
    for key in ("near_y_offset_raw", "finger_length_raw", "far_enclosure_raw"):
        if _require_int(sdcon, key, "geometry.sdcon") < 0:
            raise RuntimeError(f"gdsgen.py: geometry.sdcon.{key} must be non-negative")
    row_scheme = raw_geometry.get("row_scheme")
    if not isinstance(row_scheme, dict):
        raise RuntimeError("gdsgen.py: geometry.row_scheme must be a JSON object")
    row_map = row_scheme.get("pmos_near_row_by_row_scheme")
    if not isinstance(row_map, dict):
        raise RuntimeError("gdsgen.py: geometry.row_scheme.pmos_near_row_by_row_scheme must be a JSON object")
    for scheme in ("4", "5"):
        if _require_int(row_map, scheme, "geometry.row_scheme.pmos_near_row_by_row_scheme") < 0:
            raise RuntimeError(f"gdsgen.py: geometry.row_scheme.pmos_near_row_by_row_scheme.{scheme} must be non-negative")
    return raw_geometry


cfg_path = os.environ.get("GDSGEN_CONFIG")
if not cfg_path or not Path(cfg_path).is_file():
    raise RuntimeError("gdsgen.py: GDSGEN_CONFIG must name an existing JSON file")
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
if not isinstance(cfg, dict):
    raise RuntimeError("gdsgen.py: GDSGEN_CONFIG root must be a JSON object")
output_dir = cfg.get("output_dir", output_dir)
cells = cfg.get("cells", cfg.get("filenames", cells))
mh_order = cfg.get("mh_order", mh_order)
port_nets_map = cfg.get("port_nets", {})
geometry = _validate_geometry_config(cfg.get("geometry"))

set_track_height(geometry["track_count"], geometry["track_pitch_raw"])
ACT_BOTTOM_ANCHOR, LEGACY_ACT_CENTER_ANCHOR = set_geometry_constants(
    geometry["act_bottom_anchor_raw"],
    geometry["legacy_act_center_anchor_raw"],
)
LISD.length = geometry["sdcon"]["finger_length_raw"]
SDT.length = geometry["sdcon"]["finger_length_raw"]

if not cells:
    raise RuntimeError(
        "gdsgen.py: no cells specified. Set GDSGEN_CONFIG to a JSON file with "
        "{\"cells\": [...], \"output_dir\": ...}. (Old hardcoded default './INV_X1' "
        "was removed — silent wrong-cell generation is a critical failure mode.)"
    )

Path(output_dir).mkdir(parents=True, exist_ok=True)

for filename in cells:
	cell_name = filename.split("/")[-1]
	M0_power_rail_width = geometry["m0_power_rail_width_raw"]
	M0_power_rail_to_1st_M0_track = geometry["m0_power_rail_to_first_track_raw"]
	
	new_layout = pya.Layout()
	new_layout.dbu = 0.00025
	
	M0_layer = new_layout.layer(M0.layer_number, M0.datatype)
	outline_layer = new_layout.layer(235, 250)
	
	new_cell = new_layout.create_cell(f"{cell_name}")
	print(f"Cell name : {cell_name}")
	column_length = 0
	nets_data = {}
	combined_pmos = {}
	combined_nmos = {}
	ordered_devices = []

	order=[]

	explicit_max_track = None
	content_five_row_signal = False

	with open(filename, 'r') as file:
	    for line in file:
	        line = line.strip()

	        if line.startswith("ROW_SCHEME:"):
	            m = re.match(r'^ROW_SCHEME:\s*(\d+)$', line)
	            if m:
	                explicit_max_track = int(m.group(1))
	            continue

	        if line.startswith("PMOS:") or line.startswith("NMOS:"):
	            m = re.match(r'^(PMOS|NMOS):\s*(\d+)\s*(\[.*\])$', line)
	            if m:
	                device_type = m.group(1)
	                order.insert(0,device_type)
	                height_str = m.group(2)
	                height = int(height_str)
	                array_str = m.group(3)
	
	                device_list = eval(array_str)
	
	                if device_type == "PMOS":
	                    if height not in combined_pmos:
	                        combined_pmos[height] = []
	                    combined_pmos[height].append(device_list)
	
	                else:
	                    if height not in combined_nmos:
	                        combined_nmos[height] = []
	                    combined_nmos[height].append(device_list)
	                
	                ordered_devices.append({
	                    "type": device_type,
	                    "height": height,
	                    "devices": device_list
	                })
	
	            continue
	
	        if line.startswith("Net "):
	            if "Via positions" in line:
	                m = re.match(r'^Net\s+(\S+):\s*Via positions\s*(\[.*?\])\s*,\s*(\[.*?\])$', line)
	                if m:
	                    net_name = m.group(1)
	                    bracket_single = m.group(2).strip()
	                    bracket_double = m.group(3).strip()
	
	                    via_single_tuples = re.findall(r'\((\d+)\s*,\s*(\d+)\)', bracket_single)
	                    via_single = [(int(h), int(pos)) for (h, pos) in via_single_tuples]
	                    via_double_nums = re.findall(r'\d+', bracket_double)
	                    via_double = [int(num) for num in via_double_nums]
	
	                    if net_name not in nets_data:
	                        nets_data[net_name] = {}
	                    nets_data[net_name]["via_single"] = via_single
	                    nets_data[net_name]["via_double"] = via_double
	
	            elif ", H " in line and ", Row " in line:
	                m = re.match(r'^Net\s+(\S+),\s*H\s+(\d+),\s*Row\s+(\d+):\s*\[(.*)\]$', line)
	                if m:
	                    net_name = m.group(1)
	                    net_height = int(m.group(2))
	                    row_num = int(m.group(3))
	                    row_data_str = m.group(4)
	
	                    row_data = [x.strip() for x in row_data_str.split(',')]

	                    if net_height == 1 and row_num == 4:
	                        content_five_row_signal = True

	                    if net_height == 2:
	                        row_num -= 10

	                    if net_name not in nets_data:
	                        nets_data[net_name] = {}
	
	                    if 'rows' not in nets_data[net_name]:
	                        nets_data[net_name]['rows'] = {}
	
	                    nets_data[net_name]['rows'][net_height,row_num] = row_data
	
	                    if len(row_data) > column_length:
	                        column_length = len(row_data)
	
	            continue
	cpp = int((column_length+1)/2)
	height = int(len(ordered_devices)/2)

	if explicit_max_track is not None:
		row_scheme_five = explicit_max_track >= 5
	else:
		row_scheme_five = content_five_row_signal
	set_row_scheme(row_scheme_five)
	print(f"Row scheme for {cell_name}: {'5-row' if row_scheme_five else '4-row (legacy)'} "
	      f"(marker={explicit_max_track}, content_signal={content_five_row_signal})")

	if column_length > 0:
	    outline_box = pya.Box(0, 0, cpp * (GATE.width+GATE.pitch), GATE.length*height)
	    new_cell.shapes(outline_layer).insert(outline_box)
	
	_wm = re.search(r'_w(\d+)', cell_name)
	_W = int(_wm.group(1)) if _wm else 13
	set_cur_width(_W)
	GATE.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top)
	_sdcon_far_tight_bits = set()
	_sdcon_pmos_near_row = geometry["row_scheme"]["pmos_near_row_by_row_scheme"]["5" if row_scheme_five else "4"]
	for _net_name, _net_info in nets_data.items():
		for (_h, _row), _bits in _net_info.get('rows', {}).items():
			if _row != _sdcon_pmos_near_row:
				continue
			for _bi, _v in enumerate(_bits):
				if _v == '1':
					_sdcon_far_tight_bits.add((_h, _bi))
	for _h in combined_pmos:
		_prow = combined_pmos[_h][0]
		_nrow = combined_nmos.get(_h, [[]])[0]
		for _ci in range(0, min(len(_prow), len(_nrow)), 2):
			if _prow[_ci] == _nrow[_ci]:
				_sdcon_far_tight_bits.add((_h, _ci))
	_sdcon_near_y_offset = geometry["sdcon"]["near_y_offset_raw"]
	LISD.draw_layer_rects(new_cell, new_layout, start_x=(GATE.width+GATE.pitch)//2, y_offset=_sdcon_near_y_offset, outline_right=outline_box.right, outline_top=outline_box.top, pmos_near_via_bits=_sdcon_far_tight_bits, sdcon_geometry=geometry)
	SDT.draw_layer_rects(new_cell, new_layout, start_x=(GATE.width+GATE.pitch)//2, y_offset=_sdcon_near_y_offset, outline_right=outline_box.right, outline_top=outline_box.top, pmos_near_via_bits=_sdcon_far_tight_bits, sdcon_geometry=geometry)
	ACTIVE.width = _W * 4
	if _W > 22:
		_act_yoff = max(LEGACY_ACT_CENTER_ANCHOR - _W * 2, ACT_BOTTOM_ANCHOR)
		ACTIVE.pitch = (GATE.length - 2*_act_yoff) - _W * 8
	else:
		ACTIVE.pitch = (GATE.length - 2*ACT_BOTTOM_ANCHOR) - _W * 8
		_act_yoff = ACT_BOTTOM_ANCHOR
	ACTIVE.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=_act_yoff, outline_right=outline_box.right, outline_top=outline_box.top)
	Nselect.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top, order=order)
	Pselect.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top, order=order)
	WELL.draw_layer_rects(new_cell, new_layout, start_x=0, y_offset=0, outline_right=outline_box.right, outline_top=outline_box.top, order=order)
	_VT_LAYER = {'elvt': 94, 'ulvt': 95, 'svt': 96, 'hvt': 97, 'sramvt': 98}
	_vtm = re.search(r'_w\d+_([a-z]+?)(?:_DH_[NP])?$', cell_name)
	if not _vtm:
	    raise ValueError(f"gdsgen: cannot parse Vt flavor from cell name '{cell_name}' (expected ..._w<NN>_<flavor>)")
	_vt = _vtm.group(1)
	if _vt != 'lvt':
	    if _vt not in _VT_LAYER:
	        raise ValueError(f"gdsgen: unknown Vt flavor '{_vt}' in cell '{cell_name}'; known={sorted(_VT_LAYER) + ['lvt']}")
	    _vt_layer = new_layout.layer(_VT_LAYER[_vt], 0)
	    new_cell.shapes(_vt_layer).insert(pya.Box(0, 0, outline_box.right, outline_box.top))
	BPR.horizontal_power_gen(new_cell, new_layout, 0, geometry["bpr_rail_width_raw"], outline_box.right, outline_box.top, GATE.length)
	_bpr_pin = new_layout.layer(8, 251)
	new_cell.shapes(_bpr_pin).insert(pya.Box(0, -64, outline_box.right, 64))
	new_cell.shapes(_bpr_pin).insert(pya.Box(0, outline_box.top-64, outline_box.right, outline_box.top+64))
	_dummy_layer = new_layout.layer(4, 0)
	_dhw = GATE.width // 2
	new_cell.shapes(_dummy_layer).insert(pya.Box(-_dhw, 0, _dhw, outline_box.top))
	new_cell.shapes(_dummy_layer).insert(pya.Box(outline_box.right - _dhw, 0, outline_box.right + _dhw, outline_box.top))
	_gate_pitch = GATE.width + GATE.pitch
	_gcut_layer = new_layout.layer(5, 0)
	new_cell.shapes(_gcut_layer).insert(pya.Box(-_dhw, -20, outline_box.right+_dhw, 20))
	new_cell.shapes(_gcut_layer).insert(pya.Box(-_dhw, outline_box.top-20, outline_box.right+_dhw, outline_box.top+20))
	_gcut_half_w = _gate_pitch // 2 + 8
	_gcut_via_margin = 8
	_pmos_near_row = geometry["row_scheme"]["pmos_near_row_by_row_scheme"]["5" if row_scheme_five else "4"]
	for _mh in sorted(set(combined_pmos) | set(combined_nmos)):
	    for _pmos_list in combined_pmos.get(_mh, []):
	        for _nmos_list in combined_nmos.get(_mh, []):
	            _ncols = min((len(_pmos_list) - 1) // 2, (len(_nmos_list) - 1) // 2)
	            for _mk in range(_ncols):
	                _pn = str(_pmos_list[2 * _mk + 1]).lower()
	                _nn = str(_nmos_list[2 * _mk + 1]).lower()
	                _xc = (_mk + 1) * _gate_pitch
	                if _pn == _nn:
	                    if _pn == "dummy":
	                        new_cell.shapes(_dummy_layer).insert(pya.Box(_xc - _dhw, 0, _xc + _dhw, outline_box.top))
	                    continue
	
	                _row1_top = _m0_track_ybot(1, _mh, M0_power_rail_width, M0_power_rail_to_1st_M0_track) + M0.width
	                _row2_bot = _m0_track_ybot(_pmos_near_row, _mh, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	                _gcut_y_lo = _row1_top + _gcut_via_margin
	                _gcut_y_hi = _row2_bot - _gcut_via_margin
	                _act_lo_top = _act_yoff + ACTIVE.width
	                _act_hi_bot = _act_lo_top + ACTIVE.pitch
	                _act_clear = 40
	                _gcut_y_lo = max(_gcut_y_lo, _act_lo_top + _act_clear)
	                _gcut_y_hi = min(_gcut_y_hi, _act_hi_bot - _act_clear)
	                assert _gcut_y_hi - _gcut_y_lo >= 40, (
	                    f"GCUT internal cut: row1-row{_pmos_near_row} gap too small ({_row2_bot - _row1_top} raw) "
	                    f"to fit a DRC-legal (>=10nm/40raw) cut with {_gcut_via_margin}-raw via "
	                    f"clearance on cell '{cell_name}', column {_mk} (row_scheme_five={row_scheme_five})"
	                )
	                new_cell.shapes(_gcut_layer).insert(pya.Box(
	                    _xc - _gcut_half_w, _gcut_y_lo, _xc + _gcut_half_w, _gcut_y_hi))
	                if _pn == "dummy":
	                    new_cell.shapes(_dummy_layer).insert(pya.Box(_xc - _dhw, _gcut_y_hi, _xc + _dhw, outline_box.top))
	                if _nn == "dummy":
	                    new_cell.shapes(_dummy_layer).insert(pya.Box(_xc - _dhw, 0, _xc + _dhw, _gcut_y_lo))
	LISD.horizontal_power_gen(new_cell, new_layout, 0, M0_power_rail_width, outline_box.right, outline_box.top,GATE.length, order,combined_pmos,combined_nmos, sdcon_geometry=geometry)
	V0.power_gen(new_cell, new_layout, LISD.width, LISD.pitch, M0_power_rail_width, outline_box.right, outline_box.top,GATE.length, order, combined_pmos, combined_nmos)
	
	M0.draw_horizontal(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	V1.draw_V1(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	V2.draw_V2(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	V0.draw_V0(new_cell,new_layout,nets_data,combined_pmos,combined_nmos,M0_power_rail_width,M0_power_rail_to_1st_M0_track,mh_order)
	M1.draw_M1_custom(new_cell,new_layout,M0_power_rail_width,M0_power_rail_to_1st_M0_track, nets_data)
	M2.draw_horizontal(new_cell, new_layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
	
	M0.merge_layers_or(new_cell,new_layout)
	M1.merge_layers_or(new_cell,new_layout)
	M2.merge_layers_or(new_cell,new_layout)
	GATE.merge_layers_or(new_cell,new_layout)
	LISD.merge_layers_or(new_cell,new_layout)
	GCUT.merge_layers_or(new_cell,new_layout)
	
	cell_port_nets = port_nets_map.get(cell_name)
	if cell_port_nets is None:
		_cdl_path = filename + ".cdl"
		if os.path.isfile(_cdl_path):
			with open(_cdl_path, encoding="utf-8") as _cf:
				_cdl_text = _cf.read()
			_m = re.search(r"(?im)^\.subckt\s+\S+\s+(.*)$", _cdl_text)
			if _m:
				cell_port_nets = _m.group(1).split()
	M0.create_labels(new_cell,new_layout,nets_data,M0_power_rail_width,M0_power_rail_to_1st_M0_track,10,outline_box.right,order=order,port_nets=cell_port_nets)

	heal_m05_corners(new_cell, new_layout)
	heal_m04_tips(new_cell, new_layout)

	new_layout.transform(pya.ICplxTrans(0.5))
	new_layout.dbu = 0.0005
	new_layout.write(f"{output_dir}/{cell_name}.gds")
