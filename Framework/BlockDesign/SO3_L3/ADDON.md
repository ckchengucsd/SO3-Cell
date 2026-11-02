# Using SO3_L3_addon with the L3 Fusion Compiler flow

Keep the original L3 library and `SO3_L3_addon` as separate libraries. The addon
is not automatically enabled by the existing production scripts. Apply the
mandatory [baseline Full Adder restrictions](../../../README.md#fusion-compiler--full-adder-dont_use-requirement)
when adapting your local flow.

The existing `initial/rm_setup/design_setup.tcl` uses `REFERENCE_LIBRARY` for
LEF inputs and `CLIB_REFERENCE_LIBRARY_CONFIGURATION_FLOW_DB_LIST` and
`FUSION_REFERENCE_LIBRARY_DB_LIST` for DB inputs. The latter fusion-library
creation path also needs matching frame/NDM inputs. This example appends to
existing lists, preserving the baseline L3 and technology inputs:

```tcl
# Set this to the absolute SO3-Cell checkout path before using the example.
# set SO3_CELL_ROOT /absolute/path/to/SO3-Cell
set addon_db  [file join $SO3_CELL_ROOT Enablement db SO3_L3_addon.db]
set addon_lef [file join $SO3_CELL_ROOT Enablement lef SO3_L3_addon.lef]
set addon_gds [file join $SO3_CELL_ROOT Enablement gds SO3_L3_addon.gds]
set addon_cdl [file join $SO3_CELL_ROOT Enablement cdl SO3_L3_addon.cdl]

# Apply after existing setup assigns these lists, before library creation.
lappend REFERENCE_LIBRARY $addon_lef
lappend CLIB_REFERENCE_LIBRARY_CONFIGURATION_FLOW_DB_LIST $addon_db
lappend FUSION_REFERENCE_LIBRARY_DB_LIST $addon_db

# If this flow uses stream merging for physical signoff:
lappend STREAM_FILES_FOR_MERGE $addon_gds
# Use $addon_cdl as an additional cell-netlist input in the site's LVS setup.
```

Use the DB list corresponding to the reference-library creation mode you select.
Appending a DB alone does not create a complete physical reference library.
For the frame/NDM paths, generate a matching addon frame/reference library using
the site's existing technology and library preparation procedure, then add it to
`CLIB_REFERENCE_LIBRARY_CONFIGURATION_FLOW_FRAME_LIST` or
`FUSION_REFERENCE_LIBRARY_FRAM_LIST`, respectively. The repository's
`create_fusion_reference_library.tcl` consumes frame and DB lists together.
No addon NDM/frame is supplied, and this example does not prescribe technology
initialization commands. Confirm `coresite` and `coresite_DH_N` site support,
layers, units and power-pin handling in your technology setup.

Retain `Enablement/lib/SO3_L3_addon.lib` as the readable timing model;
`Enablement/db/SO3_L3_addon.db` is its compiled logical/timing view. Use
`Enablement/lef/SO3_L3_addon.lef` as the physical abstract input where the
chosen library-preparation flow accepts LEF. The GDS and CDL are physical/signoff
deliverables, not timing libraries. Configure LVS and stream-out/merge inputs
with both the original L3 views and addon views as required by the site flow.

After loading the libraries, apply the README's exact baseline FA exclusions
before `compile_fusion` and all implementation optimization. Leave the addon
`FA_X1_NEW` available only after validating it in your flow. Inspect actual
loaded library names if reference-library preparation changes their naming.
This documentation example has not been executed in Fusion Compiler.
