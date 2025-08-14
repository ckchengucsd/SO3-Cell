import pya
import glob

# List of GDS files to be merged
#gds_files = ["file1.gds", "file2.gds", "file3.gds"]  # Add your file names here
# Use a wildcard to select GDS files
gds_files = glob.glob("leaf_cell/*.gds")  # This will select all GDS files in the current directory
#gds_files = glob.glob("new_cell/*.gds")  # This will select all GDS files in the current directory

# Create a new layout
merged_layout = pya.Layout()

## Check if there are any files to process
#if len(gds_files) > 0:
#    # Read the first file to set the dbu for the merged layout
#    first_layout = pya.Layout()
#    first_layout.read(gds_files[0])
#    merged_layout.dbu = first_layout.dbu
#
#    # Create a new top cell
#    top_cell = merged_layout.create_cell("TopCell")
#
#    for gds_file in gds_files:
#        # Read each file into a separate cell
#        file_layout = pya.Layout()
#        file_layout.read(gds_file)
#        
#        # Assume each file has only one top cell, and import this cell
#        source_top_cell = file_layout.top_cell()
#        new_cell = merged_layout.create_cell(source_top_cell.name)
#        
#        # Copy the contents of the file's top cell into the new cell
#        new_cell.copy_tree(source_top_cell)
#
#        # Place the new cell into the merged layout's top cell
#        trans = pya.Trans(pya.Trans.R0, 0, 0)  # No translation, change if necessary
#        top_cell.insert(pya.CellInstArray(new_cell.cell_index(), trans))
#
#    # Save the merged layout to a new GDS file
#    merged_layout.write("merged_layout.gds")

# Set the dbu for the merged layout based on the first file
if len(gds_files) > 0:
    first_layout = pya.Layout()
    first_layout.read(gds_files[0])
    merged_layout.dbu = first_layout.dbu

# Process each GDS file
for gds_file in gds_files:
    # Read each file into a temporary layout
    file_layout = pya.Layout()
    file_layout.read(gds_file)
    
    # Copy the contents of each file's top cell into the merged layout
    for cell in file_layout.each_cell():
        new_cell = merged_layout.create_cell(cell.name)
        new_cell.copy_tree(cell)

# Save the merged layout to a new GDS file
merged_layout.write("SO3_L2.gds")
