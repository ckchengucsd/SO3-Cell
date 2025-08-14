import pya
from collections import defaultdict

class LayerInfo:
    def __init__(self, layer_number, datatype, width, pitch, length):
        self.layer_number = layer_number
        self.datatype = datatype
        self.width = width
        self.pitch = pitch
        self.length = length
    
    # Method to draw rectangles for the layer
    def draw_layer_rects(self, cell, layout, start_x, y_offset, outline_right, outline_top, order=None):
        layer = layout.layer(self.layer_number, self.datatype)
        i = 0
        if self.layer_number == 17 or self.layer_number == 88:
            detector = GATE.length/2
        else :
            detector = self.length

        if self.layer_number == 2:
            while y_offset + i*(self.width+self.pitch) <= outline_top:
                y_ofs = y_offset + i*(self.width+self.pitch)
                rect = pya.Box(0, y_ofs, outline_right, y_ofs + int(self.width))
                cell.shapes(layer).insert(rect)
                i += 1
       
        elif self.layer_number == 11:
            y_ofs = y_offset + i*GATE.length
            while y_ofs <= outline_top:
                rect1 = pya.Box(0, y_ofs, outline_right, y_ofs + int(self.width))
                y_ofs_next = y_ofs + self.width+self.pitch
                rect2 = pya.Box(0, y_ofs_next, outline_right, y_ofs_next + int(self.width))
                cell.shapes(layer).insert(rect1)
                cell.shapes(layer).insert(rect2)
                i += 1
                y_ofs = y_offset + i*GATE.length
        elif self.layer_number == 12 or self.layer_number == 13 or self.layer_number == 1:
            for index,var in enumerate(order):
                print (index,var)
                if (var == 'NMOS' and self.layer_number == 12) or (var == 'PMOS' and (self.layer_number == 13 or self.layer_number == 1)):
                    y_ofs = y_offset+index*GATE.length/2
                    rect = pya.Box(0, y_ofs, outline_right, y_ofs + int(self.width))
                    cell.shapes(layer).insert(rect)
        else:
            while i * detector < outline_top:
                x = start_x
                if self.layer_number == 17 or self.layer_number == 88:
                    if i % 2 == 0:
                        y_ofs = y_offset + i * detector
                    else :
                        y_ofs = (i+1) * detector - self.length - y_offset
                else:
                    y_ofs = y_offset + i * self.length
                while x <= outline_right:
                    left = int(x - self.width / 2)
                    right = int(x + self.width / 2)
                    if self.layer_number == 88:
                        rect = pya.Box(left, y_ofs+4, right, y_ofs + int(self.length)-4)
                    else:
                        rect = pya.Box(left, y_ofs, right, y_ofs + int(self.length))
                    x += self.width + self.pitch
                    if self.layer_number == 10:
                        if left < 0 or right > outline_right:
                            cell.shapes(layer).insert(rect)
                    else:
                        cell.shapes(layer).insert(rect)
                i += 1
    
    def horizontal_power_gen(self, cell, layout, start_y, power_rail_width, outline_right, outline_top, cell_height,order,combined_pmos,combined_nmos):
        layer = layout.layer(self.layer_number, self.datatype)
        y = start_y
        if self.layer_number == 10:
            while y <= outline_top:
                if y ==0 or y == outline_top:
                    rect = pya.Box(0, y-power_rail_width / 4, outline_right, y+power_rail_width / 4)
                    cell.shapes(layer).insert(rect)
                y += cell_height
        x=self.width+self.pitch
        for h in combined_pmos:
            for i,net in enumerate(combined_pmos[h][0]):
                if i % 2 == 1 and self.layer_number == 10:
                    #print(net,combined_nmos[h][0][i])
                    if net != combined_nmos[h][0][i]:
                        rect = pya.Box(x*(i+1)/2-x/2, cell_height*(h-1)+cell_height/2-10, x*(i+1)/2+x/2, cell_height*(h-1)+cell_height/2+10)
                        cell.shapes(layer).insert(rect)
                    if net == 'dummy':
                        rect = pya.Box(x*(i+1)/2-self.width/2, cell_height*(h-1), x*(i+1)/2+self.width/2, cell_height*h)
                        cell.shapes(layer).insert(rect)
                elif i % 2 == 0 and self.layer_number == 17:
                    if net == combined_nmos[h][0][i]:
                        rect = pya.Box(x*(i+1)/2-self.width/2, cell_height*(h-1)+cell_height/2-60, x*(i+1)/2+self.width/2, cell_height*(h-1)+cell_height/2+60)
                        cell.shapes(layer).insert(rect)
        if len(order) > 2:
            #print (order)
            if order[1] == 'PMOS':
                target_mos = combined_pmos
            elif order[1] == 'NMOS':
                target_mos = combined_nmos
            #print (target_mos)
            if self.layer_number == 10:
                left_side = pya.Box(0, cell_height-power_rail_width/4, 0+x/2, cell_height+power_rail_width/4)
                right_side = pya.Box(outline_right-x/2, cell_height-power_rail_width/4, outline_right, cell_height+power_rail_width/4)
                cell.shapes(layer).insert(left_side)
                cell.shapes(layer).insert(right_side)
            for i,net in enumerate(target_mos[1][0]):
                if i % 2 == 1 and self.layer_number == 10:
                    if net != target_mos[2][0][i]:
                        rect = pya.Box(x*(i+1)/2-x/2, cell_height-power_rail_width/4, x*(i+1)/2+x/2, cell_height+power_rail_width/4)
                        cell.shapes(layer).insert(rect)
                elif i % 2 == 0 and self.layer_number == 17:
                    if net == target_mos[2][0][i]:
                        rect = pya.Box(x*(i+1)/2-self.width/2, cell_height-80, x*(i+1)/2+self.width/2, cell_height+80)
                        cell.shapes(layer).insert(rect)
        if self.layer_number == 17:
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
        # Define layer objects
        target_layer = layout.layer(self.layer_number, self.datatype)  # Assuming datatype=0

        # Create regions for both layers
        region = pya.Region(cell.shapes(target_layer))

        # Perform logical OR (union) of the two regions
        merged_region = region | region
        merged_region.merge()

        # Clear original layers
        cell.shapes(target_layer).clear()
        #print(f"Cleared original layer {target_layer}")

        # Copy merged region back to layer1
        cell.shapes(target_layer).insert(merged_region)

# width, pitch, length
#GATE = LayerInfo(7, 0, 12, 168, 576) # 3nm
#SDB = LayerInfo(77, 0, 12, 168, 576) # 3nm
GATE = LayerInfo(7, 0, 64, 116, 576) # PROBE
GCUT = LayerInfo(10, 0, 64, 116, 576) # PROBE
LISD = LayerInfo(17, 0, 64, 116, 184)
SDT = LayerInfo(88, 0, 64, 116, 184)
FIN = LayerInfo(2, 0, 24, 72, 0) # no length -> always from left to right
ACTIVE = LayerInfo(11, 0, 184, 104, 0) # no length -> always from left to right
Nselect = LayerInfo(12, 0, 288, 0, 0) # no length -> always from left to right / no pitch
Pselect = LayerInfo(13, 0, 288, 0, 0) # no length -> always from left to right / no pitch
WELL = LayerInfo(1, 0, 288, 0, 0) # no length -> always from left to right / no pitch
PSUB = LayerInfo(3, 0, 288, 0, 0) # no length -> always from left to right / no pitch

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
    
    # New method to draw M0 based on the data
    def draw_horizontal(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
        layer = layout.layer(self.layer_number, self.datatype)
        y_start = M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track  # Starting y-coordinate for row 0
        for net_name, net_info in nets_data.items():
            #print (net_name,net_info['rows'])
            if net_name == 'buffer' or net_name == 'eol': ### have to find better way to exclude this
                continue  # Skip 'buffer' nets
            for height, row in net_info['rows']:
                if self.layer_number == 15:
                    #target_row =[0,1,2,3,4]
                    target_row =[0,1,2,3]
                elif self.layer_number == 20:
                    #target_row =[5,6,7,8,9]
                    target_row =[4,5,6,7]
                if row in target_row:
                    #print (net_name,height,row,net_info['rows'][height,row])
                    if self.layer_number == 20:
                        row_to_use = row - 4
                    elif self.layer_number == 15:
                        row_to_use = row
                    y_offset = y_start + row_to_use * (self.width + self.pitch) + GATE.length * (height-1)  # Calculate y-coordinate for the row
            #    elif self.layer_number == 20:
            #        y_offset = y_start + (row-4) * (self.width + self.pitch)  # Calculate y-coordinate for the row
                    x_positions = []
                    start_idx = None
                    for idx, val in enumerate(net_info['rows'][height,row]):
                        if val == '1' and start_idx is None:
                            start_idx = idx+1
                        elif val == '0' and start_idx is not None:
                            x_positions.append((start_idx, idx))
                            start_idx = None
                    #print (net_name,row,x_positions)
                    if start_idx is not None:
                        x_positions.append((start_idx, len(net_info['rows'][height,row])))
                    #print (net_name,row,x_positions,len(net_info['rows'][height,row]),net_info['rows'][height,row])
                    # Draw rectangles for each continuous '1's
                    for start, end in x_positions:
                        x_left = start * 90
                        #x_right = (end + 1) * 90  # (end + 1) because range is inclusive
                        x_right = end * 90 
                        rect = pya.Box(x_left, y_offset, x_right, y_offset + self.width)
                        print (net_name,x_left,x_right)
                        cell.shapes(layer).insert(rect)
    
    # Method to merge two layers using logical OR
    def merge_layers_or(self, cell, layout):
        # Define layer objects
        target_layer = layout.layer(self.layer_number, self.datatype)  # Assuming datatype=0

        # Create regions for both layers
        region = pya.Region(cell.shapes(target_layer))

        # Perform logical OR (union) of the two regions
        merged_region = region | region
        merged_region.merge()

        # Clear original layers
        cell.shapes(target_layer).clear()
        #print(f"Cleared original layer {target_layer}")

        # Copy merged region back to layer1
        cell.shapes(target_layer).insert(merged_region)

    # Method to draw M1 based on existing M1 x-coordinates
    def draw_M1_custom(self, cell, layout, M0_power_rail_width, M0_power_rail_to_1st_M0_track, nets_data):
        # Retrieve the M1 layer
        m1_layer = layout.layer(self.layer_number, self.datatype)
        via_positions={}
        via_positions_dh={}
        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue  # Skip 'buffer' nets
            #print(net_info)
            via_positions[net_name] = net_info['via_single']
            via_positions_dh[net_name] = net_info['via_double']
        
        # Iterate through existing M1 shapes to extract x-coordinates
        existing_m1_shapes = cell.shapes(m1_layer).each()
        #x_centers = set()
        x_center_and_ys={}
        for shape in existing_m1_shapes:
            bbox = shape.bbox()
            x_center = (bbox.left + bbox.right) / 2
            #x_centers.add(x_center)
            if x_center not in x_center_and_ys:
                x_center_and_ys[x_center] = set()
            x_center_and_ys[x_center].add(bbox.top)
            x_center_and_ys[x_center].add(bbox.bottom)
        
        sorted_x_center_and_ys = {x: sorted(ys) for x, ys in x_center_and_ys.items()}
        # Debug: Print extracted x_centers
        #print(f"Extracted M1 x_centers: {x_centers}")
        #print(f"Extracted M1 x_centers: {x_center_and_ys}")
        #print(f"Extracted M1 x_centers(sorted): {sorted_x_center_and_ys}")
        #print(via_positions)
        #print(via_positions_dh)

        for net in via_positions:
            if via_positions[net]:
                for height,via in via_positions[net]:
                    #print (net,height,via,sorted_x_center_and_ys[via*30])
                    # Define min/max y-values in the specified range
                    y_values_in_range = [
                        y for y in sorted_x_center_and_ys[via * 30]
                        if (height - 1) * GATE.length <= y <= height * GATE.length
                    ]
                    # Ensure list is not empty before applying min/max
                    min_y = min(y_values_in_range)
                    max_y = max(y_values_in_range)
                    
                    # MAR Tunning ###
                    # Constants
                    LOWER_RANGE = (96, 384)
                    UPPER_RANGE = (192, 480)
                    THRESHOLD = 288
                    print (via,min_y,max_y,y_values_in_range)
                    # Adjust min_y and max_y based on threshold
                    if max_y - min_y < THRESHOLD:
                        # Shift values by (height - 1) * GATE.length
                        shift = (height - 1) * GATE.length
                        lower_min, lower_max = LOWER_RANGE[0] + shift, LOWER_RANGE[1] + shift
                        upper_min, upper_max = UPPER_RANGE[0] + shift, UPPER_RANGE[1] + shift

                    # Check overlap conditions
                        lower_overlap = (max_y <= lower_max and min_y >= lower_min)
                        upper_overlap = (max_y <= upper_max and min_y >= upper_min)

                        if lower_overlap and upper_overlap:
                            min_y, max_y = lower_min, lower_max  # 96~384 priority
                        elif upper_overlap:
                            min_y, max_y = upper_min, upper_max
                        elif lower_overlap:
                            min_y, max_y = lower_min, lower_max

                    rect = pya.Box(
                        via*30 - (self.width / 2),
                        min_y,
                        via*30 + (self.width / 2),
                        max_y
                    )
                    # Insert the rectangle into M1 layer
                    cell.shapes(m1_layer).insert(rect)
                    print(f"Drew M1 rectangle at x={via*30}, y=({min_y}, {max_y})")
        for net in via_positions_dh:
            if via_positions_dh[net]:
                for via in via_positions_dh[net]:
                    #print (via,sorted_x_center_and_ys[via*30])
                    rect = pya.Box(
                        via*30 - (self.width / 2),
                        sorted_x_center_and_ys[via*30][0],
                        via*30 + (self.width / 2),
                        sorted_x_center_and_ys[via*30][-1]
                    )
                    # Insert the rectangle into M1 layer
                    cell.shapes(m1_layer).insert(rect)
                    print(f"Drew M1 rectangle at x={via*30}, y=({sorted_x_center_and_ys[via*30][0]}, {sorted_x_center_and_ys[via*30][-1]})")

    # **New Method to Create Labels Based on Net Names**
    def create_labels(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track, label_font_height, outline_right, order=None):
        # Define the label layer using layer_number and label_datatype
        label_layer = layout.layer(self.layer_number, self.label_datatype)
        y_start = M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track  # Starting y-coordinate for row 0
        via_positions={}
        via_positions_dh={}
        for net_name, net_info in nets_data.items():
            # **Filter Nets by Name:**
            # Only process nets whose names start with an uppercase alphabet
            if not net_name or not net_name[0].isupper():
                continue  # Skip nets not starting with uppercase
            print (f"make label for {net_name}!")
            via_positions[net_name] = net_info['via_single']
            via_positions_dh[net_name] = net_info['via_double']
            #print (net_info)
            #print (net_info['via_double'],via_positions_dh[net_name])
            # Check if there are any non-empty via positions
            #net_has_vias = any(
            #    str(pos[1]).strip() if isinstance(pos[1], str) else bool(pos[1])
            #    for pos in via_positions[net_name] + via_positions_dh[net_name]
            #    if isinstance(pos, tuple)
            #)
            net_has_vias = bool(via_positions.get(net_name)) or bool(via_positions_dh.get(net_name))
            #if net_has_vias:
            #    print(f"{net_name} has via positions!")
            #else:
            #    print(f"{net_name} has NO via positions.")
            if not net_has_vias:
                # **Case 1:** No via locations -> Place M0 Label
                #print(f"{net_name} M0 label!")
                for height, row in net_info['rows']:
                    target_row =[0,1,2,3,4]
                    if row in target_row:
                        #print (net_name,height,row,net_info['rows'][height,row])
                        y_center = y_start + self.width/2 + row * (self.width + self.pitch) + GATE.length * (height-1)  # Calculate y-coordinate for the row
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
                            #text_shape = pya.Text(net_name, pya.Trans(pya.Trans.R0, x_center, y_center))
                            text_shape = pya.Text(net_name, x_center, y_center)
                            text_shape.text_size = label_font_height  # Adjust font height
                            cell.shapes(label_layer).insert(text_shape)
                            print(f"Placed M0 label for net '{net_name}' at ({x_center}, {y_center})")

            else:
                is_m2_flag = 0
                for height, row in net_info['rows']:
                    m2_label_layer = layout.layer(M2.layer_number, M2.label_datatype)
                    #target_row =[5,6,7,8,9]
                    target_row =[4,5,6,7]
                    if row in target_row:
                        y_center = y_start + self.width/2 + (row-4) * (self.width + self.pitch) + GATE.length * (height-1)  # Calculate y-coordinate for the row
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
                            #text_shape = pya.Text(net_name, pya.Trans(pya.Trans.R0, x_center, y_center))
                            text_shape = pya.Text(net_name, x_center, y_center)
                            text_shape.text_size = label_font_height # Adjust font height
                            cell.shapes(m2_label_layer).insert(text_shape)
                            print(f"Placed M2 label for net '{net_name}' at ({x_center}, {y_center})")
                if is_m2_flag == 0:
                    #print(f"Placed M1 label for net '{net_name}'")
                    #print(net_has_vias)
                    m1_label_layer = layout.layer(M1.layer_number, M1.label_datatype)
                    via_for_m1 = via_positions[net_name] + via_positions_dh[net_name]
                    if via_positions[net_name]:
                        height, via_x = via_positions[net_name][0]
                        y_center = (height-1)*GATE.length + GATE.length/2
                        x_center = via_x*30 
                        text_shape = pya.Text(net_name, x_center, y_center)
                        text_shape.text_size = label_font_height # Adjust font height
                        cell.shapes(m1_label_layer).insert(text_shape)
                        print(f"Placed M1 label for net '{net_name}' at ({x_center}, {y_center})")
                    else :
                        via_x = via_positions_dh[net_name][0]
                        y_center = GATE.length
                        x_center = via_x*30 
                        text_shape = pya.Text(net_name, x_center, y_center)
                        text_shape.text_size = label_font_height # Adjust font height
                        cell.shapes(m1_label_layer).insert(text_shape)
                        print(f"Placed M1 label for net '{net_name}' at ({x_center}, {y_center})")
            
            power_center = outline_right/2 
            for index,var in enumerate(order):
                #print (index,var)
                div = index // 2
                rem = index % 2
                #print (index,div,rem)
                y_center = (div+rem)*GATE.length
                if var == 'NMOS' :
                    label_text='VSS'
                    psub_text_shape = pya.Text(label_text, power_center, y_center)
                    psub_text_shape.text_size = label_font_height # Adjust font height
                    cell.shapes(layout.layer(PSUB.layer_number, 251)).insert(psub_text_shape)
                    m0_text_shape = pya.Text(label_text, power_center, y_center)
                    m0_text_shape.text_size = label_font_height # Adjust font height
                    cell.shapes(layout.layer(self.layer_number, self.label_datatype)).insert(m0_text_shape)
                elif var == 'PMOS' :
                    label_text='VDD'
                    psub_text_shape = pya.Text(label_text, power_center, y_center)
                    psub_text_shape.text_size = label_font_height # Adjust font height
                    cell.shapes(layout.layer(WELL.layer_number, 251)).insert(psub_text_shape)
                    m0_text_shape = pya.Text(label_text, power_center, y_center)
                    m0_text_shape.text_size = label_font_height # Adjust font height
                    cell.shapes(layout.layer(self.layer_number, self.label_datatype)).insert(m0_text_shape)

#                # **Case 2:** With Via Locations
#                # Determine if rows 4-7 are used
#                rows_used = any('1' in net_info.get(f'Row {row}', []) for row in range(4, 8))
#
#                if not rows_used:
#                    # **Subcase 2a:** Rows 4-7 unused -> Place M1 Label
#                    x_centers = []
#
#                    for row in range(0, 4):
#                        row_data = net_info.get(f'Row {row}', [])
#                        if not row_data:
#                            continue  # Skip if no data for the row
#
#                        indices = [idx for idx, val in enumerate(row_data) if val == '1']
#                        if not indices:
#                            continue  # Skip if no '1's in the row
#
#                        # Calculate x_center as the midpoint between first and last '1's
#                        first_idx = indices[0]
#                        last_idx = indices[-1]
#                        x_center = ((first_idx + 1) * (GATE.width + GATE.pitch) / 2 + 
#                                    (last_idx + 1) * (GATE.width + GATE.pitch) / 2) / 2
#                        x_centers.append(x_center)
#
#                    if x_centers:
#                        # Average x_centers if multiple rows have '1's
#                        x_label = sum(x_centers) / len(x_centers)
#                        y_label = GATE.length / 2  # Fixed y_center for M1 labels
#
#                        # Create and insert the label with specified font height
#                        text_shape = pya.Text(net_name, pya.Trans(pya.Trans.R0, x_label, y_label))
#                        text_shape.text_size = label_font_height  # Adjust font height
#                        cell.shapes(label_layer).insert(text_shape)
#                        print(f"Placed M1 label for net '{net_name}' at ({x_label}, {y_label})")
#                else:
#                    # **Subcase 2b:** Rows 4-7 used -> Place M2 Labels
#                    for row in range(4, 8):
#                        row_data = net_info.get(f'Row {row}', [])
#                        if not row_data:
#                            continue  # Skip if no data for the row
#
#                        indices = [idx for idx, val in enumerate(row_data) if val == '1']
#                        if not indices:
#                            continue  # Skip if no '1's in the row
#
#                        # Calculate x_center as the midpoint between first and last '1's
#                        first_idx = indices[0]
#                        last_idx = indices[-1]
#                        x_center = ((first_idx + 1) * (GATE.width + GATE.pitch) / 2 + 
#                                    (last_idx + 1) * (GATE.width + GATE.pitch) / 2) / 2
#
#                        # Calculate y_center based on the row number
#                        y_center = (M0_power_rail_width / 2) + M0_power_rail_to_1st_M0_track + \
#                                (self.width / 2) + (row - 4) * (self.width + self.pitch)
#
#                        # Create and insert the label with specified font height
#                        text_shape = pya.Text(net_name, pya.Trans(pya.Trans.R0, x_center, y_center))
#                        text_shape.text_size = label_font_height  # Adjust font height
#                        cell.shapes(label_layer).insert(text_shape)
#                        print(f"Placed M2 label for net '{net_name}' at ({x_center}, {y_center})")

M0 = MetalLayerInfo(15, 0, 56, 40, 251)  # Label datatype for M0 / layer_number, datatype, width, pitch, label_datatype
M1 = MetalLayerInfo(19, 0, 60, 60, 251)  # Label datatype for M1
M2 = MetalLayerInfo(20, 0, 56, 40, 251)  # Label datatype for M2

class ViaLayerInfo:
    def __init__(self, layer_number, datatype, width, ovllower, ovlupper):
        self.layer_number = layer_number
        self.datatype = datatype
        self.width = width
        self.ovllower = ovllower
        self.ovlupper = ovlupper

    # Method to draw V1 vias
    def draw_V1(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
        via_layer = layout.layer(self.layer_number, self.datatype)
        M0_layer = layout.layer(M0.layer_number, M0.datatype)
        M1_layer = layout.layer(M1.layer_number, M1.datatype)

        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue  # Skip 'buffer' nets
            via_positions = net_info['via_single']
            via_positions_dh = net_info['via_double']
            #print(net_name,via_positions)
            #print(net_name,via_positions_dh)
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
                x_center = pos * (M1.width+M1.pitch)/4  # x-coordinate for the via center
                #y_start = (via_height-1)*GATE.length
                #print (y_start,x_center)
                # Find the rows where the net has '1's and x_center falls within the '1's range
                for height, row in net_info['rows']:
                    if self.layer_number == 18:
                        #target_row =[0,1,2,3,4]
                        target_row =[0,1,2,3]
                    elif self.layer_number == 21:
                        #target_row =[5,6,7,8,9]
                        target_row =[4,5,6,7]
                    if row in target_row and height in via_height and '1' in net_info['rows'][height,row]:
                        #print (row,height,"Wow")
                        
                        x_positions = []
                        start_idx = None
                        for idx, val in enumerate(net_info['rows'][height,row]):
                            if val == '1' and start_idx is None:
                                start_idx = idx+1
                            elif val == '0' and start_idx is not None:
                                x_positions.append((start_idx, idx))
                                start_idx = None
                        #print (net_name,row,x_positions)
                        if start_idx is not None:
                            x_positions.append((start_idx, len(net_info['rows'][height,row])))
                        #print (x_positions)
                        for x_b in x_positions:
                            min_index = min(x_b)
                            max_index = max(x_b)
                            x_min = min_index * (GATE.width+GATE.pitch)/2
                            x_max = max_index * (GATE.width+GATE.pitch)/2
                            if x_min <= x_center <= x_max and row not in rows_with_via[height]:
                                print (f"real v1 found {net_name},{row},{height},{pos_str}")
                                rows_with_via[height].append(row)

                        #indices_with_1 = [i for i, val in enumerate(net_info['rows'][height,row]) if val == '1']
                        #min_index = min(indices_with_1)
                        #max_index = max(indices_with_1)
                        #x_min = (min_index + 1) * (GATE.width+GATE.pitch)/2
                        #x_max = (max_index + 1) * (GATE.width+GATE.pitch)/2  # +1 because '1's span up to (max_index + 1) * 90
                        #print(net_name,row,x_min,x_max,pos,x_center)
                        #if x_min <= x_center <= x_max and row not in rows_with_via[height]:
                        # x_center falls within the range of '1's in this row
                            #print (f"v1 found {net_name},{row},{height},{pos_str},{indices_with_1}")
                            #rows_with_via[height].append(row)
                if not rows_with_via[via_height[0]]:
                    continue  # No suitable row found for this via position
                #print(rows_with_via)
                # For each suitable row, draw the via and overlaps
                for h in via_height:
                    for row in rows_with_via[h]:
                        y_center = GATE.length*(h-1) + M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track + M0.width/2 + row * (M0.width + M0.pitch)
                        #print (row,x_center,y_center)
                        # Draw the via
                        via_size = self.width / 2
                        via_box = pya.Box(
                            x_center - via_size, y_center - via_size,
                            x_center + via_size, y_center + via_size
                        )
                        cell.shapes(via_layer).insert(via_box)
    
                        # Draw overlaps with M0 and M1
                        # Lower overlap with M0 (horizontal extension)
                        M0_box = pya.Box(
                            x_center - via_size - self.ovllower,
                            y_center - M0.width / 2,
                            x_center + via_size + self.ovllower,
                            y_center + M0.width / 2
                        )
                        cell.shapes(M0_layer).insert(M0_box)
    
                        # Upper overlap with M1 (vertical extension)
                        M1_box = pya.Box(
                            x_center - M1.width / 2,
                            y_center - via_size - self.ovlupper,
                            x_center + M1.width / 2,
                            y_center + via_size + self.ovlupper
                        )
                        cell.shapes(M1_layer).insert(M1_box)

    # Method to draw V2 vias
    def draw_V2(self, cell, layout, nets_data, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
        print ("V2 Start")
        via_layer = layout.layer(self.layer_number, self.datatype)
        M2_layer = layout.layer(M2.layer_number, M2.datatype)
        M1_layer = layout.layer(M1.layer_number, M1.datatype)

        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue  # Skip 'buffer' nets

            via_positions = net_info['via_single']
            via_positions_dh = net_info['via_double']
            #print(net_name,via_positions)
            
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
                x_center = pos * (M1.width+M1.pitch)/4  # x-coordinate for the via center
                #print (net_name,pos,x_center)
                
                # Find the rows where the net has '1's and x_center falls within the '1's range
                for height, row in net_info['rows']:
                    if self.layer_number == 18:
                        #target_row =[0,1,2,3,4]
                        target_row =[0,1,2,3]
                    elif self.layer_number == 21:
                        #target_row =[5,6,7,8,9]
                        target_row =[4,5,6,7]
                    if row in target_row and height in via_height and '1' in net_info['rows'][height,row]:
                        #print (row,height,"Wow")
                        indices_with_1 = [i for i, val in enumerate(net_info['rows'][height,row]) if val == '1']
                        min_index = min(indices_with_1)
                        max_index = max(indices_with_1)
                        x_min = (min_index + 1) * (GATE.width+GATE.pitch)/2
                        x_max = (max_index + 1) * (GATE.width+GATE.pitch)/2  # +1 because '1's span up to (max_index + 1) * 90
                        print(net_name,row,x_min,x_max,pos,x_center)
                        if x_min <= x_center <= x_max and row not in rows_with_via[height]:
                        # x_center falls within the range of '1's in this row
                            rows_with_via[height].append(row)
                if not rows_with_via[via_height[0]]:
                    continue  # No suitable row found for this via position
                print(rows_with_via)
                # For each suitable row, draw the via and overlaps
                for h in via_height:
                    for row in rows_with_via[h]:
                        m2_row = row-4
                        y_center = GATE.length*(h-1) + M0_power_rail_width / 2 + M0_power_rail_to_1st_M0_track + M2.width/2 + m2_row * (M2.width + M2.pitch)
                        print (m2_row,x_center,y_center)
                        # Draw the via
                        via_size = self.width / 2
                        via_box = pya.Box(
                            x_center - via_size, y_center - via_size,
                            x_center + via_size, y_center + via_size
                        )
                        cell.shapes(via_layer).insert(via_box)
    
                        # Draw overlaps with M2 and M1
                        # Lower overlap with M2 (horizontal extension)
                        M2_box = pya.Box(
                            x_center - via_size - self.ovllower,
                            y_center - M2.width / 2,
                            x_center + via_size + self.ovllower,
                            y_center + M2.width / 2
                        )
                        cell.shapes(M2_layer).insert(M2_box)
    
                        # Upper overlap with M1 (vertical extension)
                        M1_box = pya.Box(
                            x_center - M1.width / 2,
                            y_center - via_size - self.ovlupper,
                            x_center + M1.width / 2,
                            y_center + via_size + self.ovlupper
                        )
                        cell.shapes(M1_layer).insert(M1_box)

    # Method to draw V0 vias
    def draw_V0(self, cell, layout, nets_data, combined_pmos, combined_nmos, M0_power_rail_width, M0_power_rail_to_1st_M0_track):
        via_layer = layout.layer(self.layer_number, self.datatype)
        LIG_layer = layout.layer(LIG.layer_number, LIG.datatype)
        M0_layer = layout.layer(M0.layer_number, M0.datatype)

        # Process each net
        for net_name, net_info in nets_data.items():
            if net_name == 'buffer' or net_name == 'eol':
                continue  # Skip 'buffer' nets
            #print (net_name,net_info)
            print(f"Processing Net: {net_name}")
            #print(combined_pmos,combined_nmos)
            # Determine if net is in combined_pmos or combined_nmos
            in_pmos={}
            in_nmos={}
            for h in combined_pmos:
                #print (combined_pmos[h],combined_nmos[h])
                in_pmos[h] = net_name in combined_pmos[h][0]
                in_nmos[h] = net_name in combined_nmos[h][0]
            #print (in_pmos,in_nmos)
            if not any(in_pmos.values()) and not any(in_nmos.values()):
                continue  # Skip nets not in pmos or nmos

            # Extract positions from combined_pmos and combined_nmos
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
            # Determine overlapping, pmos-only, and nmos-only positions
                overlapping_positions[h] = set(pmos_positions[h]) & set(nmos_positions[h])
                pmos_only_positions[h] = set(pmos_positions[h]) - overlapping_positions[h]
                nmos_only_positions[h] = set(nmos_positions[h]) - overlapping_positions[h]
            # Calculate allowed x_centers
                overlapping_x_centers[h] = [(pos+1) * interval for pos in overlapping_positions[h]]
                pmos_only_x_centers[h] = [(pos+1) * interval for pos in pmos_only_positions[h]]
                nmos_only_x_centers[h] = [(pos+1) * interval for pos in nmos_only_positions[h]]

            # Debug prints
            #print(f"PMOS Positions: {pmos_positions}")
            #print(f"NMOS Positions: {nmos_positions}")
            #print(f"Overlapping Positions: {overlapping_positions}")
            #print(f"PMOS-Only Positions: {pmos_only_positions}")
            #print(f"NMOS-Only Positions: {nmos_only_positions}")
            #print (overlapping_x_centers)
            #print (pmos_only_x_centers)
            #print (nmos_only_x_centers)

            # Function to check if a position is within a '1' segment in a given row
            def is_within_segment(pos, height, row_number):
                row_data = net_info['rows'][height,row_number]
                if not row_data:
                    return False  # No data for this row

                # Identify '1' segments
                segments = []
                start_idx = None
                for idx, val in enumerate(row_data):
                    if val == '1' and start_idx is None:
                        start_idx = idx
                    elif (val == '0' or idx == len(row_data) - 1) and start_idx is not None:
                        end_idx = idx if val == '1' and idx == len(row_data) - 1 else idx - 1
                        segments.append((start_idx, end_idx))
                        start_idx = None
                #print (pos,row_number,segments)
                # Check if pos is within any segment
                for segment in segments:
                    if segment[0]+1 <= pos <= segment[1]+1:
                        return True
                return False
            
            M0_MAX_TRACK = 4
            # Place V0 vias for overlapping positions in rows 0-1 and 2-3
            for h in combined_pmos:
                for x_center in overlapping_x_centers[h]:
                    if x_center % (2*interval) == 0:
                        make_lig = 1
                    else :
                        make_lig = 0
                    # Place in NMOS rows (0-1)
                    for row_number in range(0, M0_MAX_TRACK):
                        if is_within_segment(x_center/interval, h, row_number):
                            y_center = (
                                (h-1)*GATE.length +
                                (M0_power_rail_width / 2) +
                                M0_power_rail_to_1st_M0_track +
                                (M0.width / 2) +
                                row_number * (M0.width + M0.pitch)
                            )
                            # Draw the V0 via
                            via_size = self.width / 2
                            via_box = pya.Box(
                                x_center - via_size,
                                y_center - via_size,
                                x_center + via_size,
                                y_center + via_size
                            )
                            cell.shapes(via_layer).insert(via_box)
                            if make_lig == 1:
                                cell.shapes(LIG_layer).insert(via_box)

                            # Draw overlaps with M0 (upper overlap)
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

                # Place V0 vias for PMOS-only positions in rows 2-3
                # N first h 1 -> 2,3 / h 2 -> 0,1
                list=[[2,3],[0,1]]
                # P first h 1 -> 0,1 / h 2 -> 2,3
                #list=[[0,1],[2,3]]
                for x_center in pmos_only_x_centers[h]:
                    if x_center % (2*interval) == 0:
                        make_lig = 1
                    else :
                        make_lig = 0
                    for row_number in list[h-1]:
                        if is_within_segment(x_center/interval, h, row_number):
                            y_center = (
                                (h-1)*GATE.length +
                                (M0_power_rail_width / 2) +
                                M0_power_rail_to_1st_M0_track +
                                (M0.width / 2) +
                                row_number * (M0.width + M0.pitch)
                            )
                            # Draw the V0 via
                            via_size = self.width / 2
                            via_box = pya.Box(
                                x_center - via_size,
                                y_center - via_size,
                                x_center + via_size,
                                y_center + via_size
                            )
                            cell.shapes(via_layer).insert(via_box)
                            if make_lig == 1:
                                cell.shapes(LIG_layer).insert(via_box)
    
                            # Draw overlaps with M0 (upper overlap)
                            M0_box = pya.Box(
                                x_center - via_size - self.ovlupper,
                                y_center - M0.width / 2,
                                x_center + via_size + self.ovlupper,
                                y_center + M0.width / 2
                            )
                            cell.shapes(M0_layer).insert(M0_box)
                            print(f"Placed V0 via at x={x_center}, y={y_center} in PMOS-only Row {row_number}")

                # Place V0 vias for NMOS-only positions in rows 0-1
                # N first h 1 -> 0,1 / h 2 -> 2,3
                list=[[0,1],[2,3]]
                # P first h 1 -> 2,3 / h 2 -> 0,1
                #list=[[2,3],[0,1]]
                for x_center in nmos_only_x_centers[h]:
                    if x_center % (2*interval) == 0:
                        make_lig = 1
                    else :
                        make_lig = 0
                    for row_number in list[h-1]:
                        if is_within_segment(x_center/interval, h, row_number):
                            y_center = (
                                (h-1)*GATE.length +
                                (M0_power_rail_width / 2) +
                                M0_power_rail_to_1st_M0_track +
                                (M0.width / 2) +
                                row_number * (M0.width + M0.pitch)
                            )
                            # Draw the V0 via
                            via_size = self.width / 2
                            via_box = pya.Box(
                                x_center - via_size,
                                y_center - via_size,
                                x_center + via_size,
                                y_center + via_size
                            )
                            cell.shapes(via_layer).insert(via_box)
                            if make_lig == 1:
                                cell.shapes(LIG_layer).insert(via_box)
    
                            # Draw overlaps with M0 (upper overlap)
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
                    cell.shapes(layer).insert(rect)


V0 = ViaLayerInfo(14, 0, 56, 0, 20)  # Label datatype for V0=CA(LI*-M0) / layer_number, datatype, width, ovl not use, ovl w m0 
LIG = ViaLayerInfo(16, 0, 56, 0, 20)  # Label datatype for LIG / layer_number, datatype, width, ovl not use, ovl w m0
V1 = ViaLayerInfo(18, 0, 56, 20, 20)  # Label datatype for V1=V0(M0-M1) / layer_number, datatype, width, ovl w m0, ovl w m1
V2 = ViaLayerInfo(21, 0, 56, 20, 20)  # Label datatype for V2=V1(M1-M2) / layer_number, datatype, width, ovl w m1, ovl w m2
