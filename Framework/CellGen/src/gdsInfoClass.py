import pya
from collections import defaultdict

class LayerInfo:
    def __init__(self, layer_number, datatype, width, pitch, length):
        self.layer_number = layer_number
        self.datatype = datatype
        self.width = width
        self.pitch = pitch
        self.length = length

    def draw_layer_rects(self, cell, layout, start_x, y_offset, outline_right, outline_top, order=None, pmos_near_via_bits=None, sdcon_geometry=None):
        layer = layout.layer(self.layer_number, self.datatype)
        i = 0
        if self.layer_number == 10 or self.layer_number == 10:
            detector = (GATE.length // 2)
        else :
            detector = self.length

        if self.layer_number == 2:
            y_ofs = y_offset + i*GATE.length
            while y_ofs <= outline_top:
                rect1 = pya.Box(0, y_ofs, outline_right, y_ofs + int(self.width))
                y_ofs_next = y_ofs + self.width+self.pitch
                rect2 = pya.Box(0, y_ofs_next, outline_right, y_ofs_next + int(self.width))
                cell.shapes(layer).insert(rect1)
                cell.shapes(layer).insert(rect2)
                i += 1
                y_ofs = y_offset + i*GATE.length
        elif self.layer_number == 6 or self.layer_number == 7 or self.layer_number == 1:
            for index,var in enumerate(order):
                print (index,var)
                if (var == 'NMOS' and self.layer_number == 6) or (var == 'PMOS' and (self.layer_number == 7 or self.layer_number == 1)):
                    tier, half = divmod(index, 2)
                    y_ofs = y_offset + tier * GATE.length + half * (GATE.length // 2)
                    rect = pya.Box(0, y_ofs, outline_right, y_ofs + int(self.width))
                    cell.shapes(layer).insert(rect)
        else:
            if self.layer_number == 10 and _cur_W_nm is not None and _cur_W_nm > 22:
                _legacy_detector = GATE.length // 2
                _li = 0
                while _li * _legacy_detector < outline_top:
                    x = start_x
                    if _li % 2 == 0:
                        y_ofs = y_offset + _li * _legacy_detector
                    else:
                        y_ofs = (_li + 1) * _legacy_detector - self.length - y_offset
                    while x <= outline_right:
                        left = int(x - self.width / 2)
                        right = int(x + self.width / 2)
                        rect = pya.Box(left, y_ofs, right, y_ofs + int(self.length))
                        x += self.width + self.pitch
                        cell.shapes(layer).insert(rect)
                    _li += 1
                return
            if self.layer_number == 10:
                _sdcon_row_count = max(1, round(outline_top / GATE.length))
            while (i < 2 * _sdcon_row_count if self.layer_number == 10 else i * detector < outline_top):
                x = start_x
                if self.layer_number == 10 or self.layer_number == 10:
                    _sdcon_row = i // 2
                    if i % 2 == 0:
                        y_ofs = _sdcon_row * GATE.length + y_offset
                    else :
                        assert _cur_W_nm is not None, "far SDCON finger needs set_cur_width(W_nm) called before drawing"
                        if _cur_W_nm > 22:
                            _sdcon_band2_bottom = (GATE.length - LEGACY_ACT_CENTER_ANCHOR) - 6 * _cur_W_nm
                        else:
                            _sdcon_band2_bottom = (GATE.length - ACT_BOTTOM_ANCHOR - 4 * _cur_W_nm)
                        _sdcon_cfg, _sdcon_row_map = _require_sdcon_geometry(sdcon_geometry)
                        _sdcon_pmos_near_row = _sdcon_row_map["5" if _five_row_scheme() else "4"]
                        _sdcon_pmos_near_y = _m0_track_ybot(
                            _sdcon_pmos_near_row,
                            1,
                            sdcon_geometry["m0_power_rail_width_raw"],
                            sdcon_geometry["m0_power_rail_to_first_track_raw"],
                        )
                        _sdcon_far_enclosure = _sdcon_cfg["far_enclosure_raw"]
                        _sdcon_far_bottom_tight = _sdcon_row * GATE.length + (_sdcon_pmos_near_y - _sdcon_far_enclosure)
                        _sdcon_far_bottom_relaxed = _sdcon_row * GATE.length + (_sdcon_band2_bottom - _sdcon_far_enclosure)
                        _sdcon_far_top = (_sdcon_row + 1) * GATE.length - y_offset
                        _sdcon_far_height = _sdcon_row + 1
                        y_ofs = None
                else:
                    y_ofs = y_offset + i * self.length
                while x <= outline_right:
                    left = int(x - self.width / 2)
                    right = int(x + self.width / 2)
                    if self.layer_number == 10 and i % 2 == 1:
                        _col_k = int(round((x - start_x) / (self.width + self.pitch)))
                        _bits_here = {(_sdcon_far_height, 2 * _col_k), (_sdcon_far_height, 2 * _col_k + 1)}
                        _needs_tight = pmos_near_via_bits is None or bool(_bits_here & pmos_near_via_bits)
                        y_ofs = _sdcon_far_bottom_tight if _needs_tight else _sdcon_far_bottom_relaxed
                        _sdcon_this_length = _sdcon_far_top - y_ofs
                    else:
                        _sdcon_this_length = self.length
                    rect = pya.Box(left, y_ofs, right, y_ofs + int(_sdcon_this_length))
                    x += self.width + self.pitch
                    if self.layer_number == 5:
                        if left < 0 or right > outline_right:
                            cell.shapes(layer).insert(rect)
                    else:
                        cell.shapes(layer).insert(rect)
                i += 1
    
    def horizontal_power_gen(self, cell, layout, start_y, power_rail_width, outline_right, outline_top, cell_height,order,combined_pmos,combined_nmos, sdcon_geometry=None):
        layer = layout.layer(self.layer_number, self.datatype)
        y = start_y
        if self.layer_number == 5:
            while y <= outline_top:
                if y ==0 or y == outline_top:
                    rect = pya.Box(0, y-power_rail_width / 4, outline_right, y+power_rail_width / 4)
                    cell.shapes(layer).insert(rect)
                y += cell_height
        x=self.width+self.pitch
        for h in combined_pmos:
            for i,net in enumerate(combined_pmos[h][0]):
                if i % 2 == 1 and self.layer_number == 5:
                    if net != combined_nmos[h][0][i]:
                        rect = pya.Box(x*(i+1)/2-x/2, cell_height*(h-1)+cell_height/2-10, x*(i+1)/2+x/2, cell_height*(h-1)+cell_height/2+10)
                        cell.shapes(layer).insert(rect)
                    if net == 'dummy':
                        rect = pya.Box(x*(i+1)/2-self.width/2, cell_height*(h-1), x*(i+1)/2+self.width/2, cell_height*h)
                        cell.shapes(layer).insert(rect)
                elif i % 2 == 0 and self.layer_number == 10:
                    nmos_net_i = combined_nmos[h][0][i]
                    pmos_net_i = net
                    power_nets = {'VDD', 'VSS', 'dummy'}
                    if pmos_net_i == nmos_net_i:
                        assert _cur_W_nm is not None, "SDCON bridge needs set_cur_width(W_nm) called before drawing"
                        _sdcon_cfg, _sdcon_row_map = _require_sdcon_geometry(sdcon_geometry)
                        _bridge_near_top = cell_height*(h-1) + _sdcon_cfg["near_y_offset_raw"] + _sdcon_cfg["finger_length_raw"]
                        _bridge_pmos_near_row = _sdcon_row_map["5" if _five_row_scheme() else "4"]
                        _bridge_pmos_near_y = _m0_track_ybot(
                            _bridge_pmos_near_row,
                            1,
                            sdcon_geometry["m0_power_rail_width_raw"],
                            sdcon_geometry["m0_power_rail_to_first_track_raw"],
                        )
                        _bridge_far_bottom = cell_height*(h-1) + (_bridge_pmos_near_y - _sdcon_cfg["far_enclosure_raw"])
                        _bridge_overlap = _sdcon_cfg["far_enclosure_raw"]
                        rect = pya.Box(x*(i+1)/2-self.width/2, _bridge_near_top - _bridge_overlap,
                                       x*(i+1)/2+self.width/2, _bridge_far_bottom + _bridge_overlap)
                        cell.shapes(layer).insert(rect)
                    else:
                        pass
        if len(order) > 2:
            if order[1] == 'PMOS':
                target_mos = combined_pmos
            elif order[1] == 'NMOS':
                target_mos = combined_nmos
            if self.layer_number == 5:
                left_side = pya.Box(0, cell_height-power_rail_width/4, 0+x/2, cell_height+power_rail_width/4)
                right_side = pya.Box(outline_right-x/2, cell_height-power_rail_width/4, outline_right, cell_height+power_rail_width/4)
                cell.shapes(layer).insert(left_side)
                cell.shapes(layer).insert(right_side)
            for i,net in enumerate(target_mos[1][0]):
                if i % 2 == 1 and self.layer_number == 5:
                    if net != target_mos[2][0][i]:
                        rect = pya.Box(x*(i+1)/2-x/2, cell_height-power_rail_width/4, x*(i+1)/2+x/2, cell_height+power_rail_width/4)
                        cell.shapes(layer).insert(rect)
                elif i % 2 == 0 and self.layer_number == 10:
                    if net == target_mos[2][0][i]:
                        rect = pya.Box(x*(i+1)/2-self.width/2, cell_height-80, x*(i+1)/2+self.width/2, cell_height+80)
                        cell.shapes(layer).insert(rect)
        if self.layer_number == 10:
            for i,mos in enumerate(order):
                if mos == 'PMOS':
                    target_mos = combined_pmos
                elif mos == 'NMOS':
                    target_mos = combined_nmos
                if i < 2:
                    h=1
                elif 2<=i<4:
                    h=2
                for j,net in enumerate(target_mos[h][0]):
                    if i % 2 == 0:
                        y_bot=0
                        y_top=52
                    else :
                        y_bot=cell_height/2-52
                        y_top=cell_height/2
                    if net == 'VSS' or net == 'VDD':
                        rect = pya.Box(x*(j+1)/2-self.width/2, cell_height*i/2+y_bot, x*(j+1)/2+self.width/2, cell_height*i/2+y_top)
                        cell.shapes(layer).insert(rect)

    def merge_layers_or(self, cell, layout):
        target_layer = layout.layer(self.layer_number, self.datatype)

        region = pya.Region(cell.shapes(target_layer))

        merged_region = region | region
        merged_region.merge()

        cell.shapes(target_layer).clear()

        cell.shapes(target_layer).insert(merged_region)

GATE = LayerInfo(3, 0, 56, 112, 576)

ACT_BOTTOM_ANCHOR = 104

LEGACY_ACT_CENTER_ANCHOR = 166

_cur_W_nm = None

def set_cur_width(W_nm):
    global _cur_W_nm
    _cur_W_nm = W_nm


def set_geometry_constants(act_bottom_anchor_raw, legacy_act_center_anchor_raw):
    global ACT_BOTTOM_ANCHOR, LEGACY_ACT_CENTER_ANCHOR
    ACT_BOTTOM_ANCHOR = act_bottom_anchor_raw
    LEGACY_ACT_CENTER_ANCHOR = legacy_act_center_anchor_raw
    return ACT_BOTTOM_ANCHOR, LEGACY_ACT_CENTER_ANCHOR


def set_track_height(track_count, track_pitch_raw):
    GATE.length = track_count * track_pitch_raw
    Nselect.width = GATE.length // 2
    Pselect.width = GATE.length - GATE.length // 2
    WELL.width = GATE.length // 2


_row_scheme_five = False

def set_row_scheme(five_row):
    global _row_scheme_five
    _row_scheme_five = bool(five_row)

def _five_row_scheme():
    return _row_scheme_five


def _require_sdcon_geometry(geometry):
    if not isinstance(geometry, dict):
        raise RuntimeError("SDCON geometry must be supplied by GDSGEN_CONFIG.geometry")
    sdcon = geometry.get("sdcon")
    if not isinstance(sdcon, dict):
        raise RuntimeError("SDCON geometry is missing GDSGEN_CONFIG.geometry.sdcon")
    row_scheme = geometry.get("row_scheme")
    if not isinstance(row_scheme, dict):
        raise RuntimeError("SDCON geometry is missing GDSGEN_CONFIG.geometry.row_scheme")
    row_map = row_scheme.get("pmos_near_row_by_row_scheme")
    if not isinstance(row_map, dict):
        raise RuntimeError("SDCON geometry is missing pmos_near_row_by_row_scheme")
    scheme = "5" if _five_row_scheme() else "4"
    if scheme not in row_map:
        raise RuntimeError(f"SDCON geometry is missing row mapping for scheme {scheme}")
    return sdcon, row_map


VIA_X_STEP = (GATE.width + GATE.pitch) // 6
GCUT = LayerInfo(5, 0, 64, 104, 576)
LISD = LayerInfo(10, 0, 64, 104, 196)
SDT = LayerInfo(10, 0, 64, 104, 196)
ACTIVE = LayerInfo(2, 0, 52, 192, 0)
Nselect = LayerInfo(6, 0, 288, 0, 0)
Pselect = LayerInfo(7, 0, 288, 0, 0)
WELL = LayerInfo(1, 0, 288, 0, 0)

class MetalLayerInfo:
    def __init__(self, layer_number, datatype, width, pitch, label_datatype):
        self.layer_number = layer_number
        self.datatype = datatype
        self.width = width
        self.pitch = pitch
        self.label_datatype = label_datatype

    def horizontal_power_gen(self, cell, layout, start_y, power_rail_width, outline_right, outline_top, cell_height):
        layer = layout.layer(self.layer_number, self.datatype)
        y = start_y
        while y <= outline_top:
            rect = pya.Box(0, y-power_rail_width / 2, outline_right, y+power_rail_width / 2)
            cell.shapes(layer).insert(rect)
            y += cell_height
    
    def draw_horizontal(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
        layer = layout.layer(self.layer_number, self.datatype)
        y_start = M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track
        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue
            for height, row in net_info['rows']:
                if self.layer_number == 20:
                    target_row =[0,1,2,3,4] if _five_row_scheme() else [0,1,2,3]
                elif self.layer_number == 30:
                    target_row = [5,6,7,8] if _five_row_scheme() else [4,5,6,7]
                if row in target_row:
                    if self.layer_number == 30:
                        row_to_use = row - (5 if _five_row_scheme() else 4)
                        y_offset = y_start + row_to_use * (self.width + self.pitch) + GATE.length * (height-1)
                    elif self.layer_number == 20:
                        row_to_use = row
                        y_offset = _m0_track_ybot(row_to_use, height, M0_power_rail_width, M0_power_rail_to_1st_M0_track)
                    x_positions = []
                    start_idx = None
                    for idx, val in enumerate(net_info['rows'][height,row]):
                        if val == '1' and start_idx is None:
                            start_idx = idx+1
                        elif val == '0' and start_idx is not None:
                            x_positions.append((start_idx, idx))
                            start_idx = None
                    if start_idx is not None:
                        x_positions.append((start_idx, len(net_info['rows'][height,row])))
                    for start, end in x_positions:
                        x_left = start * ((GATE.width + GATE.pitch) // 2)
                        x_right = end * ((GATE.width + GATE.pitch) // 2)
                        rect = pya.Box(x_left, y_offset, x_right, y_offset + self.width)
                        print (net_name,x_left,x_right)
                        cell.shapes(layer).insert(rect)
    
    def merge_layers_or(self, cell, layout):
        target_layer = layout.layer(self.layer_number, self.datatype)

        region = pya.Region(cell.shapes(target_layer))

        merged_region = region | region
        merged_region.merge()

        cell.shapes(target_layer).clear()

        cell.shapes(target_layer).insert(merged_region)

    def draw_M1_custom(self, cell, layout, M0_power_rail_width, M0_power_rail_to_1st_M0_track, nets_data):
        m1_layer = layout.layer(self.layer_number, self.datatype)
        via_positions={}
        via_positions_dh={}
        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue
            via_positions[net_name] = net_info['via_single']
            via_positions_dh[net_name] = net_info['via_double']
        
        existing_m1_shapes = cell.shapes(m1_layer).each()
        x_center_and_ys={}
        for shape in existing_m1_shapes:
            bbox = shape.bbox()
            x_center = (bbox.left + bbox.right) / 2
            if x_center not in x_center_and_ys:
                x_center_and_ys[x_center] = set()
            x_center_and_ys[x_center].add(bbox.top)
            x_center_and_ys[x_center].add(bbox.bottom)
        
        sorted_x_center_and_ys = {x: sorted(ys) for x, ys in x_center_and_ys.items()}

        for net in via_positions:
            if via_positions[net]:
                for height,via in via_positions[net]:
                    y_values_in_range = [
                        y for y in sorted_x_center_and_ys[via * VIA_X_STEP]
                        if (height - 1) * GATE.length <= y <= height * GATE.length
                    ]
                    min_y = min(y_values_in_range)
                    max_y = max(y_values_in_range)
                    
                    LOWER_RANGE = (96, 384)
                    UPPER_RANGE = (192, 480)
                    THRESHOLD = 288
                    print (via,min_y,max_y,y_values_in_range)
                    if max_y - min_y < THRESHOLD:
                        shift = (height - 1) * GATE.length
                        lower_min, lower_max = LOWER_RANGE[0] + shift, LOWER_RANGE[1] + shift
                        upper_min, upper_max = UPPER_RANGE[0] + shift, UPPER_RANGE[1] + shift

                        lower_overlap = (max_y <= lower_max and min_y >= lower_min)
                        upper_overlap = (max_y <= upper_max and min_y >= upper_min)

                        if lower_overlap and upper_overlap:
                            min_y, max_y = lower_min, lower_max
                        elif upper_overlap:
                            min_y, max_y = upper_min, upper_max
                        elif lower_overlap:
                            min_y, max_y = lower_min, lower_max

                    rect = pya.Box(
                        via*VIA_X_STEP - (self.width / 2),
                        min_y,
                        via*VIA_X_STEP + (self.width / 2),
                        max_y
                    )
                    cell.shapes(m1_layer).insert(rect)
                    print(f"Drew M1 rectangle at x={via*VIA_X_STEP}, y=({min_y}, {max_y})")
        for net in via_positions_dh:
            if via_positions_dh[net]:
                for via in via_positions_dh[net]:
                    rect = pya.Box(
                        via*VIA_X_STEP - (self.width / 2),
                        sorted_x_center_and_ys[via*VIA_X_STEP][0],
                        via*VIA_X_STEP + (self.width / 2),
                        sorted_x_center_and_ys[via*VIA_X_STEP][-1]
                    )
                    cell.shapes(m1_layer).insert(rect)
                    print(f"Drew M1 rectangle at x={via*VIA_X_STEP}, y=({sorted_x_center_and_ys[via*VIA_X_STEP][0]}, {sorted_x_center_and_ys[via*VIA_X_STEP][-1]})")

    def create_labels(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track, label_font_height, outline_right, order=None, port_nets=None):
        label_layer = layout.layer(self.layer_number, self.label_datatype)
        y_start = M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track
        via_positions={}
        via_positions_dh={}
        for net_name, net_info in nets_data.items():
            if port_nets is not None:
                if net_name not in port_nets:
                    continue
            else:
                if not net_name or not net_name[0].isupper():
                    continue
                if net_name.startswith("NET") and net_name[3:].isdigit():
                    continue
            print (f"make label for {net_name}!")
            via_positions[net_name] = net_info['via_single']
            via_positions_dh[net_name] = net_info['via_double']
            net_has_vias = bool(via_positions.get(net_name)) or bool(via_positions_dh.get(net_name))
            if not net_has_vias:
                for height, row in net_info['rows']:
                    target_row =[0,1,2,3,4] if _five_row_scheme() else [0,1,2,3]
                    if row in target_row:
                        y_center = _m0_track_ybot(row, height, M0_power_rail_width, M0_power_rail_to_1st_M0_track) + self.width/2
                        x_positions = []
                        start_idx = None
                        for idx, val in enumerate(net_info['rows'][height,row]):
                            if val == '1' and start_idx is None:
                                start_idx = idx+1
                            elif val == '0' and start_idx is not None:
                                x_positions.append((start_idx, idx))
                                start_idx = None
                        if start_idx is not None:
                            x_positions.append((start_idx, len(net_info['rows'][height,row])))
                        if x_positions:
                            print (y_center,x_positions[0])
                            x_center = ((GATE.width + GATE.pitch)/2)*(x_positions[0][0] + x_positions[0][1]) / 2
                            text_shape = pya.Text(net_name, x_center, y_center)
                            text_shape.text_size = label_font_height
                            cell.shapes(label_layer).insert(text_shape)
                            print(f"Placed M0 label for net '{net_name}' at ({x_center}, {y_center})")

            else:
                is_m2_flag = 0
                for height, row in net_info['rows']:
                    m2_label_layer = layout.layer(M2.layer_number, M2.label_datatype)
                    target_row = [5,6,7,8] if _five_row_scheme() else [4,5,6,7]
                    if row in target_row:
                        _m2_row_ofs = 5 if _five_row_scheme() else 4
                        y_center = y_start + self.width/2 + (row-_m2_row_ofs) * (self.width + self.pitch) + GATE.length * (height-1)
                        x_positions = []
                        start_idx = None
                        for idx, val in enumerate(net_info['rows'][height,row]):
                            if val == '1' and start_idx is None:
                                start_idx = idx+1
                            elif val == '0' and start_idx is not None:
                                x_positions.append((start_idx, idx))
                                start_idx = None
                        if start_idx is not None:
                            x_positions.append((start_idx, len(net_info['rows'][height,row])))
                        if x_positions:
                            is_m2_flag += 1
                            print (y_center,x_positions[0])
                            x_center = ((GATE.width + GATE.pitch)/2)*(x_positions[0][0] + x_positions[0][1]) / 2 
                            text_shape = pya.Text(net_name, x_center, y_center)
                            text_shape.text_size = label_font_height
                            cell.shapes(m2_label_layer).insert(text_shape)
                            print(f"Placed M2 label for net '{net_name}' at ({x_center}, {y_center})")
                if is_m2_flag == 0:
                    m1_label_layer = layout.layer(M1.layer_number, M1.label_datatype)
                    via_for_m1 = via_positions[net_name] + via_positions_dh[net_name]
                    if via_positions[net_name]:
                        height, via_x = via_positions[net_name][0]
                        y_center = (height-1)*GATE.length + GATE.length/2
                        x_center = via_x*VIA_X_STEP 
                        text_shape = pya.Text(net_name, x_center, y_center)
                        text_shape.text_size = label_font_height
                        cell.shapes(m1_label_layer).insert(text_shape)
                        print(f"Placed M1 label for net '{net_name}' at ({x_center}, {y_center})")
                    else :
                        via_x = via_positions_dh[net_name][0]
                        y_center = GATE.length
                        x_center = via_x*VIA_X_STEP 
                        text_shape = pya.Text(net_name, x_center, y_center)
                        text_shape.text_size = label_font_height
                        cell.shapes(m1_label_layer).insert(text_shape)
                        print(f"Placed M1 label for net '{net_name}' at ({x_center}, {y_center})")
            
        power_center = outline_right/2
        for index,var in enumerate(order):
            div = index // 2
            rem = index % 2
            y_center = (div+rem)*GATE.length
            if var == 'NMOS' :
                label_text='VSS'
            elif var == 'PMOS' :
                label_text='VDD'
            else :
                continue
            bpr_text = pya.Text(label_text, power_center, y_center)
            bpr_text.text_size = label_font_height
            cell.shapes(layout.layer(8, 251)).insert(bpr_text)


M0 = MetalLayerInfo(20, 0, 48, 48, 251)

def _m0_track_ybot(row, height, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
    base = M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track
    pitch = M0.width + M0.pitch
    five_row = _five_row_scheme()
    if row == 0:
        y = base
    elif row == 1:
        assert _cur_W_nm is not None, "row1 needs set_cur_width(W_nm) called before drawing"
        if _cur_W_nm > 22:
            y = base + pitch
        else:
            band1_top = ACT_BOTTOM_ANCHOR + 4 * _cur_W_nm
            y = band1_top + 24
    elif (not five_row) and row == 2:
        assert _cur_W_nm is not None, "row2 needs set_cur_width(W_nm) called before drawing"
        if _cur_W_nm > 22:
            y = GATE.length - M0.width - (base + pitch)
        else:
            band2_bottom = (GATE.length - ACT_BOTTOM_ANCHOR) - 4 * _cur_W_nm
            y = band2_bottom - M0.width - 24
    elif (not five_row) and row == 3:
        y = GATE.length - M0.width - base
    elif five_row and row == 2:
        assert _cur_W_nm is not None, "row2 (middle, 5-row scheme) needs set_cur_width(W_nm)"
        band1_top = ACT_BOTTOM_ANCHOR + 4 * _cur_W_nm
        row1_top = band1_top + 24 + M0.width
        y = row1_top + 48
    elif five_row and row == 3:
        assert _cur_W_nm is not None, "row3 (5-row scheme) needs set_cur_width(W_nm)"
        band2_bottom = (GATE.length - ACT_BOTTOM_ANCHOR) - 4 * _cur_W_nm
        y = band2_bottom - M0.width - 24
    elif five_row and row == 4:
        y = GATE.length - M0.width - base
    else:
        raise ValueError(f"_m0_track_ybot: row must be 0-{4 if five_row else 3}, got {row} (five_row={five_row})")
    return y + GATE.length * (height - 1)
M1 = MetalLayerInfo(25, 0, 56, 56, 251)
M2 = MetalLayerInfo(30, 0, 56, 40, 251)
BPR = MetalLayerInfo(8, 0, 128, 0, 251)

class ViaLayerInfo:
    def __init__(self, layer_number, datatype, width, ovllower, ovlupper, height=None):
        self.layer_number = layer_number
        self.datatype = datatype
        self.width = width
        self.height = height if height is not None else width
        self.ovllower = ovllower
        self.ovlupper = ovlupper

    def draw_V1(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
        via_layer = layout.layer(self.layer_number, self.datatype)
        M0_layer = layout.layer(M0.layer_number, M0.datatype)
        M1_layer = layout.layer(M1.layer_number, M1.datatype)

        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue
            via_positions = net_info['via_single']
            via_positions_dh = net_info['via_double']
            rows_with_via = {}
            for pos_str in via_positions + via_positions_dh:
                if not pos_str:
                    continue
                if pos_str in via_positions:
                    via_height,pos = [int(pos_str[0])],int(pos_str[1])
                    rows_with_via[via_height[0]] = []
                elif pos_str in via_positions_dh:
                    via_height=[1,2]
                    pos = int(pos_str)
                    rows_with_via[via_height[0]] = []
                    rows_with_via[via_height[1]] = []
                x_center = pos * VIA_X_STEP
                for height, row in net_info['rows']:
                    if self.layer_number == 22:
                        target_row =[0,1,2,3,4] if _five_row_scheme() else [0,1,2,3]
                    elif self.layer_number == 27:
                        target_row =[4,5,6,7]
                    if row in target_row and height in via_height and '1' in net_info['rows'][height,row]:
                        
                        x_positions = []
                        start_idx = None
                        for idx, val in enumerate(net_info['rows'][height,row]):
                            if val == '1' and start_idx is None:
                                start_idx = idx+1
                            elif val == '0' and start_idx is not None:
                                x_positions.append((start_idx, idx))
                                start_idx = None
                        if start_idx is not None:
                            x_positions.append((start_idx, len(net_info['rows'][height,row])))
                        for x_b in x_positions:
                            min_index = min(x_b)
                            max_index = max(x_b)
                            x_min = min_index * (GATE.width+GATE.pitch)/2
                            x_max = max_index * (GATE.width+GATE.pitch)/2
                            if x_min <= x_center <= x_max and row not in rows_with_via[height]:
                                print (f"real v1 found {net_name},{row},{height},{pos_str}")
                                rows_with_via[height].append(row)

                if not any(rows_with_via[h] for h in via_height):
                    continue
                for h in via_height:
                    for row in rows_with_via[h]:
                        y_center = _m0_track_ybot(row, h, M0_power_rail_width, M0_power_rail_to_1st_M0_track) + M0.width/2
                        via_size = self.width / 2; via_vsize = self.height / 2
                        via_box = pya.Box(
                            x_center - via_size, y_center - via_vsize,
                            x_center + via_size, y_center + via_vsize
                        )
                        cell.shapes(via_layer).insert(via_box)
    
                        M0_box = pya.Box(
                            x_center - via_size - self.ovllower,
                            y_center - M0.width / 2,
                            x_center + via_size + self.ovllower,
                            y_center + M0.width / 2
                        )
                        cell.shapes(M0_layer).insert(M0_box)
    
                        M1_box = pya.Box(
                            x_center - M1.width / 2,
                            y_center - via_vsize - self.ovlupper,
                            x_center + M1.width / 2,
                            y_center + via_vsize + self.ovlupper
                        )
                        cell.shapes(M1_layer).insert(M1_box)

    def draw_V2(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
        print ("V2 Start")
        via_layer = layout.layer(self.layer_number, self.datatype)
        M2_layer = layout.layer(M2.layer_number, M2.datatype)
        M1_layer = layout.layer(M1.layer_number, M1.datatype)

        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue

            via_positions = net_info['via_single']
            via_positions_dh = net_info['via_double']
            
            rows_with_via = {}
            for pos_str in via_positions + via_positions_dh:
                if not pos_str:
                    continue
                if pos_str in via_positions:
                    via_height,pos = [int(pos_str[0])],int(pos_str[1])
                    rows_with_via[via_height[0]] = []
                elif pos_str in via_positions_dh:
                    via_height=[1,2]
                    pos = int(pos_str)
                    rows_with_via[via_height[0]] = []
                    rows_with_via[via_height[1]] = []
                x_center = pos * VIA_X_STEP
                
                for height, row in net_info['rows']:
                    if self.layer_number == 22:
                        target_row =[0,1,2,3,4] if _five_row_scheme() else [0,1,2,3]
                    elif self.layer_number == 27:
                        target_row = [5,6,7,8] if _five_row_scheme() else [4,5,6,7]
                    if row in target_row and height in via_height and '1' in net_info['rows'][height,row]:
                        indices_with_1 = [i for i, val in enumerate(net_info['rows'][height,row]) if val == '1']
                        min_index = min(indices_with_1)
                        max_index = max(indices_with_1)
                        x_min = (min_index + 1) * (GATE.width+GATE.pitch)/2
                        x_max = (max_index + 1) * (GATE.width+GATE.pitch)/2
                        print(net_name,row,x_min,x_max,pos,x_center)
                        if x_min <= x_center <= x_max and row not in rows_with_via[height]:
                            rows_with_via[height].append(row)
                if not any(rows_with_via[h] for h in via_height):
                    continue
                print(rows_with_via)
                for h in via_height:
                    for row in rows_with_via[h]:
                        m2_row = row - (5 if _five_row_scheme() else 4)
                        y_center = GATE.length*(h-1) + M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track + M2.width/2 + m2_row * (M2.width + M2.pitch)
                        print (m2_row,x_center,y_center)
                        via_size = self.width / 2; via_vsize = self.height / 2
                        via_box = pya.Box(
                            x_center - via_size, y_center - via_vsize,
                            x_center + via_size, y_center + via_vsize
                        )
                        cell.shapes(via_layer).insert(via_box)
    
                        M2_box = pya.Box(
                            x_center - via_size - self.ovllower,
                            y_center - M2.width / 2,
                            x_center + via_size + self.ovllower,
                            y_center + M2.width / 2
                        )
                        cell.shapes(M2_layer).insert(M2_box)
    
                        M1_box = pya.Box(
                            x_center - M1.width / 2,
                            y_center - via_vsize - self.ovlupper,
                            x_center + M1.width / 2,
                            y_center + via_vsize + self.ovlupper
                        )
                        cell.shapes(M1_layer).insert(M1_box)

    def draw_V0(self, cell, layout, nets_data, combined_pmos, combined_nmos, M0_power_rail_width, M0_power_rail_to_1st_M0_track,mh_order="N_FIRST"):
        via_layer = layout.layer(self.layer_number, self.datatype)
        LIG_layer = layout.layer(LIG.layer_number, LIG.datatype)
        M0_layer = layout.layer(M0.layer_number, M0.datatype)

        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue
            print(f"Processing Net: {net_name}")
            in_pmos={}
            in_nmos={}
            for h in combined_pmos:
                in_pmos[h] = net_name in combined_pmos[h][0]
                in_nmos[h] = net_name in combined_nmos[h][0]
            if not any(in_pmos.values()) and not any(in_nmos.values()):
                continue

            pmos_positions={}
            nmos_positions={}
            overlapping_positions={}
            pmos_only_positions={}
            nmos_only_positions={}
            overlapping_x_centers={}
            pmos_only_x_centers={}
            nmos_only_x_centers={}
            interval = (GATE.pitch + GATE.width)/2
            for h in combined_pmos:
                pmos_positions[h] = [i for i, present in enumerate(combined_pmos[h][0]) if present==net_name] if in_pmos[h] else []
                nmos_positions[h] = [i for i, present in enumerate(combined_nmos[h][0]) if present==net_name] if in_nmos[h] else []
                overlapping_positions[h] = set(pmos_positions[h]) & set(nmos_positions[h])
                pmos_only_positions[h] = set(pmos_positions[h]) - overlapping_positions[h]
                nmos_only_positions[h] = set(nmos_positions[h]) - overlapping_positions[h]
                overlapping_x_centers[h] = [(pos+1) * interval for pos in overlapping_positions[h]]
                pmos_only_x_centers[h] = [(pos+1) * interval for pos in pmos_only_positions[h]]
                nmos_only_x_centers[h] = [(pos+1) * interval for pos in nmos_only_positions[h]]


            def is_within_segment(pos, height, row_number):
                row_data = net_info['rows'][height,row_number]
                if not row_data:
                    return False

                segments = []
                start_idx = None
                for idx, val in enumerate(row_data):
                    if val == '1' and start_idx is None:
                        start_idx = idx
                    elif (val == '0' or idx == len(row_data) - 1) and start_idx is not None:
                        end_idx = idx if val == '1' and idx == len(row_data) - 1 else idx - 1
                        segments.append((start_idx, end_idx))
                        start_idx = None
                for segment in segments:
                    if segment[0]+1 <= pos <= segment[1]+1:
                        return True
                return False

            M0_MAX_TRACK = 5 if _five_row_scheme() else 4
            for h in combined_pmos:
                for x_center in overlapping_x_centers[h]:
                    if x_center % (2*interval) == 0:
                        make_lig = 1
                    else :
                        make_lig = 0
                    for row_number in range(0, M0_MAX_TRACK):
                        if is_within_segment(x_center/interval, h, row_number):
                            y_center = _m0_track_ybot(row_number, h, M0_power_rail_width, M0_power_rail_to_1st_M0_track) + (M0.width / 2)
                            via_size = self.width / 2; via_vsize = self.height / 2
                            via_box = pya.Box(
                                x_center - via_size,
                                y_center - via_vsize,
                                x_center + via_size,
                                y_center + via_vsize
                            )
                            if make_lig == 1:
                                cell.shapes(LIG_layer).insert(pya.Box(x_center - LIG.width/2, y_center - LIG.height/2, x_center + LIG.width/2, y_center + LIG.height/2))
                            else:
                                cell.shapes(via_layer).insert(via_box)

                            M0_box = pya.Box(
                                x_center - via_size - self.ovlupper,
                                y_center - M0.width / 2,
                                x_center + via_size + self.ovlupper,
                                y_center + M0.width / 2
                            )
                            cell.shapes(M0_layer).insert(M0_box)
                            if row_number < 2:
                                print(f"Placed V0 via at x={x_center}, y={y_center} in NMOS Row {row_number}")
                            else :
                                print(f"Placed V0 via at x={x_center}, y={y_center} in PMOS Row {row_number}")

                _pmos_pair = [3, 4] if _five_row_scheme() else [2, 3]
                if mh_order == "P_FIRST":
                    row_map = [[0, 1], _pmos_pair]
                else:
                    row_map = [_pmos_pair, [0, 1]]
                for x_center in pmos_only_x_centers[h]:
                    if x_center % (2*interval) == 0:
                        make_lig = 1
                    else :
                        make_lig = 0
                    for row_number in row_map[h-1]:
                        if is_within_segment(x_center/interval, h, row_number):
                            y_center = _m0_track_ybot(row_number, h, M0_power_rail_width, M0_power_rail_to_1st_M0_track) + (M0.width / 2)
                            via_size = self.width / 2; via_vsize = self.height / 2
                            via_box = pya.Box(
                                x_center - via_size,
                                y_center - via_vsize,
                                x_center + via_size,
                                y_center + via_vsize
                            )
                            if make_lig == 1:
                                cell.shapes(LIG_layer).insert(pya.Box(x_center - LIG.width/2, y_center - LIG.height/2, x_center + LIG.width/2, y_center + LIG.height/2))
                            else:
                                cell.shapes(via_layer).insert(via_box)
    
                            M0_box = pya.Box(
                                x_center - via_size - self.ovlupper,
                                y_center - M0.width / 2,
                                x_center + via_size + self.ovlupper,
                                y_center + M0.width / 2
                            )
                            cell.shapes(M0_layer).insert(M0_box)
                            print(f"Placed V0 via at x={x_center}, y={y_center} in PMOS-only Row {row_number}")

                _pmos_pair = [3, 4] if _five_row_scheme() else [2, 3]
                if mh_order == "P_FIRST":
                    row_map = [_pmos_pair, [0, 1]]
                else:
                    row_map = [[0, 1], _pmos_pair]
                for x_center in nmos_only_x_centers[h]:
                    if x_center % (2*interval) == 0:
                        make_lig = 1
                    else :
                        make_lig = 0
                    for row_number in row_map[h-1]:
                        if is_within_segment(x_center/interval, h, row_number):
                            y_center = _m0_track_ybot(row_number, h, M0_power_rail_width, M0_power_rail_to_1st_M0_track) + (M0.width / 2)
                            via_size = self.width / 2; via_vsize = self.height / 2
                            via_box = pya.Box(
                                x_center - via_size,
                                y_center - via_vsize,
                                x_center + via_size,
                                y_center + via_vsize
                            )
                            if make_lig == 1:
                                cell.shapes(LIG_layer).insert(pya.Box(x_center - LIG.width/2, y_center - LIG.height/2, x_center + LIG.width/2, y_center + LIG.height/2))
                            else:
                                cell.shapes(via_layer).insert(via_box)
    
                            M0_box = pya.Box(
                                x_center - via_size - self.ovlupper,
                                y_center - M0.width / 2,
                                x_center + via_size + self.ovlupper,
                                y_center + M0.width / 2
                            )
                            cell.shapes(M0_layer).insert(M0_box)
                            print(f"Placed V0 via at x={x_center}, y={y_center} in NMOS-only Row {row_number}")
    
    def power_gen(self, cell, layout, width, pitch, power_rail_width, outline_right, outline_top, cell_height,order,combined_pmos,combined_nmos):
        layer = layout.layer(self.layer_number, self.datatype)
        x=width+pitch
        for i,mos in enumerate(order):
            if mos == 'PMOS':
                target_mos = combined_pmos
            elif mos == 'NMOS':
                target_mos = combined_nmos
            if i < 2:
                h=1
            elif 2<=i<4:
                h=2
            for j,net in enumerate(target_mos[h][0]):
                if i % 2 == 0:
                    y_bot=0
                    y_top=power_rail_width/2
                else :
                    y_bot=cell_height/2-power_rail_width/2
                    y_top=cell_height/2
                if net == 'VSS' or net == 'VDD':
                    rect = pya.Box(x*(j+1)/2-self.width/2, cell_height*i/2+y_bot, x*(j+1)/2+self.width/2, cell_height*i/2+y_top)
                    vbpr_layer = layout.layer(9, 0)
                    _bpr_half = 64
                    _vy0 = (_bpr_half - 44) if i % 2 == 0 else (cell_height - _bpr_half)
                    cell.shapes(vbpr_layer).insert(pya.Box(x*(j+1)/2-32, _vy0, x*(j+1)/2+32, _vy0+44))


V0 = ViaLayerInfo(11, 0, 52, 0, 20, 48)
LIG = ViaLayerInfo(12, 0, 56, 0, 20, 48)
V1 = ViaLayerInfo(22, 0, 56, 32, 20, 48)
V2 = ViaLayerInfo(27, 0, 56, 20, 20)


def heal_m05_corners(cell, layout, m0_layernum=20, m0_dt=0,
                     via_layernums=(11, 12, 22), thresh=60, enc=16):
    import math
    m0l = layout.layer(m0_layernum, m0_dt)
    reg = pya.Region(cell.shapes(m0l)); reg.merge()
    box_rects, other_polys = [], []
    for poly in reg.each():
        if poly.is_box():
            b = poly.bbox(); box_rects.append([b.left, b.right, b.bottom, b.top])
        else:
            other_polys.append(poly.dup())
    vias = []
    for vn in via_layernums:
        for sh in cell.shapes(layout.layer(vn, 0)).each():
            b = sh.bbox(); vias.append((b.left, b.right, b.bottom, b.top))

    def xo(a0, a1, b0, b1):
        return min(a1, b1) > max(a0, b0)

    healed = 0
    n = len(box_rects)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            A, B = box_rects[i], box_rects[j]
            if A[1] >= B[0]:
                continue
            if xo(A[2], A[3], B[2], B[3]):
                continue
            xgap = B[0] - A[1]
            ygap = (B[2] - A[3]) if B[2] > A[3] else (A[2] - B[3])
            if ygap <= 0:
                continue
            if math.hypot(xgap, ygap) >= thresh:
                continue
            need = math.sqrt(max(0.0, thresh * thresh - ygap * ygap))
            delta = int(math.ceil(need - xgap))
            if delta <= 0:
                continue
            newAr = A[1] - delta
            okA = (newAr - A[0]) >= 96 and all(
                v[1] <= newAr - enc
                for v in vias if xo(v[0], v[1], A[0], A[1]) and xo(v[2], v[3], A[2], A[3]))
            if okA:
                A[1] = newAr; healed += 1; continue
            newBl = B[0] + delta
            okB = (B[1] - newBl) >= 96 and all(
                v[0] >= newBl + enc
                for v in vias if xo(v[0], v[1], B[0], B[1]) and xo(v[2], v[3], B[2], B[3]))
            if okB:
                B[0] = newBl; healed += 1
    def _diag_corners(rs):
        out = []
        for a in range(len(rs)):
            for b in range(a + 1, len(rs)):
                A, B = rs[a], rs[b]
                xg = max(A[0], B[0]) - min(A[1], B[1])
                yg = max(A[2], B[2]) - min(A[3], B[3])
                if xg <= 0 or yg <= 0:
                    continue
                if math.hypot(xg, yg) < thresh:
                    out.append((a, b))
        return out

    def _same_track_gap(rs, k):
        r, g = rs[k], []
        for o_i, o in enumerate(rs):
            if o_i == k or not xo(o[2], o[3], r[2], r[3]):
                continue
            g.append(o[0] - r[1] if o[0] >= r[1] else (r[0] - o[1] if o[1] <= r[0] else -1))
        return min(g) if g else None

    for (a, b) in _diag_corners(box_rects):
        A, B = box_rects[a], box_rects[b]
        li, ri = (a, b) if A[1] < B[0] else (b, a)
        before = len(_diag_corners(box_rects))
        for who in (li, ri):
            trial = [r[:] for r in box_rects]
            if who == li:
                trial[li][1] = box_rects[ri][0]
            else:
                trial[ri][0] = box_rects[li][1]
            r = trial[who]
            if (r[1] - r[0]) < 96:
                continue
            g = _same_track_gap(trial, who)
            if g is not None and g < 68:
                continue
            if any(xo(v[2], v[3], r[2], r[3]) and xo(v[0], v[1], r[0], r[1])
                   and not xo(v[0], v[1], box_rects[who][0], box_rects[who][1])
                   for v in vias):
                continue
            if len(_diag_corners(trial)) >= before:
                continue
            box_rects = trial
            healed += 1
            break

    if healed:
        cell.shapes(m0l).clear()
        for r in box_rects:
            cell.shapes(m0l).insert(pya.Box(r[0], r[2], r[1], r[3]))
        for poly in other_polys:
            cell.shapes(m0l).insert(poly)
        print(f"[heal_m05] resolved {healed} diagonal M0.5 corner(s)")
    return healed


def heal_m04_tips(cell, layout, m0_layernum=20, m0_dt=0,
                   via_layernums=(11, 12, 22), thresh=68, enc=16):
    m0l = layout.layer(m0_layernum, m0_dt)
    reg = pya.Region(cell.shapes(m0l)); reg.merge()
    box_rects, other_polys = [], []
    for poly in reg.each():
        if poly.is_box():
            b = poly.bbox(); box_rects.append([b.left, b.right, b.bottom, b.top])
        else:
            other_polys.append(poly.dup())
    vias = []
    for vn in via_layernums:
        for sh in cell.shapes(layout.layer(vn, 0)).each():
            b = sh.bbox(); vias.append((b.left, b.right, b.bottom, b.top))

    def xo(a0, a1, b0, b1):
        return min(a1, b1) > max(a0, b0)

    healed = 0
    n = len(box_rects)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            A, B = box_rects[i], box_rects[j]
            if A[1] >= B[0]:
                continue
            if not xo(A[2], A[3], B[2], B[3]):
                continue
            gap = B[0] - A[1]
            if gap >= thresh:
                continue
            delta = thresh - gap
            newAr = A[1] - delta
            okA = (newAr - A[0]) >= 96 and all(
                v[1] <= newAr - enc
                for v in vias if xo(v[0], v[1], A[0], A[1]) and xo(v[2], v[3], A[2], A[3]))
            if okA:
                A[1] = newAr; healed += 1; continue
            newBl = B[0] + delta
            okB = (B[1] - newBl) >= 96 and all(
                v[0] >= newBl + enc
                for v in vias if xo(v[0], v[1], B[0], B[1]) and xo(v[2], v[3], B[2], B[3]))
            if okB:
                B[0] = newBl; healed += 1
    if healed:
        cell.shapes(m0l).clear()
        for r in box_rects:
            cell.shapes(m0l).insert(pya.Box(r[0], r[2], r[1], r[3]))
        for poly in other_polys:
            cell.shapes(m0l).insert(poly)
        print(f"[heal_m04] resolved {healed} same-track M0.4 gap(s)")
    return healed
