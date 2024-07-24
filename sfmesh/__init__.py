version = {
    "major": 1,
    "minor": 0,
    "type": 0,
}

import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    FloatProperty,
    EnumProperty,
)
from bpy_extras.io_utils import (
    ExportHelper,
    orientation_helper,
    axis_conversion,
)
from bpy.types import (
    Operator,
)


def write_header(self, buffer, objects, use_mesh_modifiers=False):
    import struct

    print("Writing header")
    buffer.write(
        struct.pack("<BBB", version["major"], version["minor"], version["type"])
    )                                                                                   # <version>
    # No options defined in this version of the spec
    buffer.write(struct.pack("<I", 0))                                                  # <options>
    num_objects = sum(1 for obj in objects if obj.type == "MESH")
    buffer.write(struct.pack("<I", num_objects))                                        ## <num-objects>
    for obj in objects:
        if obj.mode == "EDIT":
            obj.update_from_editmode()

        if use_mesh_modifiers:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            mesh_owner = obj.evaluated_get(depsgraph)
        else:
            mesh_owner = obj

        try:
            mesh = mesh_owner.to_mesh()
        except RuntimeError:
            return

        if mesh is None:
            return

        mesh.calc_loop_triangles()

        num_tris = len(mesh.loop_triangles)
        if num_tris >= 2**16:
            self.report({"WARNING"}, f"Object {obj.name} has too many triangles!")

        # Write object metadata
        obj_name = obj.name.encode("utf-8")
        buffer.write(struct.pack("<I", len(obj_name)))                                  ### <name-length>
        buffer.write(obj_name)                                                          ### <name>
        buffer.write(struct.pack("<H", num_tris))                                       ### <triangle-count>

        mesh_owner.to_mesh_clear()


def write_objects(self, buffer, objects, global_matrix, use_mesh_modifiers=False):
    import struct
    import bmesh

    print("Writing object data")
    for obj in objects:
        if obj.mode == "EDIT":
            obj.update_from_editmode()

        if use_mesh_modifiers:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            mesh_owner = obj.evaluated_get(depsgraph)
        else:
            mesh_owner = obj

        try:
            mesh = mesh_owner.to_mesh()
        except RuntimeError:
            return

        if mesh is None:
            return

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free

        mat = global_matrix @ obj.matrix_world
        mesh.transform(mat)
        if mat.is_negative:
            mesh.flip_normals()
        mesh.calc_loop_triangles()
        mesh.calc_tangents()

        print(f"Writing object '{obj.name}' with {len(mesh.vertices)} vertices")

        # Write triangles
        for triangle in mesh.loop_triangles:
            for loop_index in reversed(triangle.loops):
                loop = mesh.loops[loop_index]
                vertex_index = loop.vertex_index
                vertex = mesh.vertices[vertex_index]
                uv = mesh.uv_layers.active.data[loop_index].uv
                buffer.write(
                    struct.pack("<3f", vertex.co.x, vertex.co.y, vertex.co.z)
                )                                                                       # <position>
                buffer.write(
                    struct.pack(
                        "<3f", vertex.normal.x, vertex.normal.y, vertex.normal.z
                    )
                )                                                                       # <normal>
                buffer.write(struct.pack("<2f", uv.x, uv.y))                            # <uv>
                buffer.write(
                    struct.pack(
                        "<3f", loop.tangent[0], loop.tangent[1], loop.tangent[2]
                    )
                )                                                                       # <tangent>
        mesh_owner.to_mesh_clear()


def write_sfmesh_raw(self, buffer, objects, global_matrix, use_mesh_modifiers=False):
    import struct

    print("Writing SFMesh...")
    write_header(self, buffer, objects, use_mesh_modifiers)
    write_objects(self, buffer, objects, global_matrix, use_mesh_modifiers)
    print("Done")


def write_sfmesh(
    self,
    filepath,
    objects,
    global_matrix,
    use_mesh_modifiers=False,
    write_raw_file=False,
):
    import io
    import lzma
    import base64

    with io.BytesIO() as buffer:
        write_sfmesh_raw(self, buffer, objects, global_matrix, use_mesh_modifiers)

        if write_raw_file:
            with open(filepath, "wb") as file:
                file.write(buffer.getvalue())
        else:
            buffer_value = buffer.getvalue()

            # LZMA shenanigans for GLua compatibility...
            uncompressed_size = len(buffer_value)
            lzc_string = lzma.compress(buffer_value, format=lzma.FORMAT_ALONE, preset=9)
            lzc_string = (
                lzc_string[:5]
                + uncompressed_size.to_bytes(8, "little")
                + lzc_string[13:]
            )

            b64_string = base64.b64encode(lzc_string)
            with open(filepath, "wb") as file:
                file.write(b'return "')
                file.write(b64_string)
                file.write(b'"')


@orientation_helper(axis_forward="Y", axis_up="Z")
class ExportSFMesh(Operator, ExportHelper):
    bl_idname = "export.sfmesh"
    bl_label = "Export SFMesh"
    bl_description = """Export to SFMesh format"""

    filename_ext = ""
    filter_glob = StringProperty(
        default="*.txt",
        options={"*.txt", "*.sfmesh"},
    )

    use_selection: BoolProperty(
        name="Selection Only",
        description="Export selected objects only",
        default=False,
    )

    global_scale: FloatProperty(
        name="Scale",
        min=0.01,
        max=1000.0,
        default=1.0,
    )

    use_scene_unit: BoolProperty(
        name="Scene Unit",
        description="Use scene units as defined by Blender",
        default=True,
    )

    use_mesh_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Apply modifiers before saving",
        default=True,
    )

    batch_mode: EnumProperty(
        name="Batch Mode",
        items=(
            ("OFF", "Off", "All data in one file"),
            ("OBJECT", "Object", "One file per object"),
        ),
    )

    write_raw_file: BoolProperty(
        name="Write raw .SFMesh file",
        description="Only write uncompressed binary mesh data",
        default=False,
    )

    @property
    def check_extension(self):
        return self.batch_mode == "OFF"

    def execute(self, context):
        import os
        from mathutils import Matrix

        keywords = self.as_keywords(
            ignore=(
                "axis_forward",
                "axis_up",
                "use_selection",
                "global_scale",
                "use_mesh_modifiers",
                "batch_mode",
            ),
        )

        filepath_ext = ".sfmesh" if self.write_raw_file else ".txt"
        self.filepath = bpy.path.ensure_ext(self.filepath, filepath_ext)

        scene = context.scene
        if self.use_selection:
            objects = context.selected_objects
        else:
            objects = scene.objects

        global_scale = self.global_scale
        if scene.unit_settings.system != "NONE" and self.use_scene_unit:
            global_scale *= scene.unit_settings.scale_length / 0.0254

        global_matrix = axis_conversion(
            to_forward=self.axis_forward,
            to_up=self.axis_up,
        ).to_4x4() @ Matrix.Scale(global_scale, 4)

        if self.batch_mode == "OFF":
            write_sfmesh(
                self,
                filepath=self.filepath,
                objects=objects,
                global_matrix=global_matrix,
                use_mesh_modifiers=self.use_mesh_modifiers,
                write_raw_file=self.write_raw_file,
            )
        elif self.batch_mode == "OBJECT":
            prefix = os.path.splitext(self.filepath)[0]
            for object in objects:
                obj_filepath = prefix + bpy.path.clean_name(object.name) + filepath_ext
                write_sfmesh(
                    self,
                    filepath=obj_filepath,
                    objects=[object],
                    global_matrix=global_matrix,
                    use_mesh_modifiers=self.use_mesh_modifiers,
                    write_raw_file=self.write_raw_file,
                )

        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "batch_mode")

        layout.prop(operator, "use_selection")

        layout.prop(operator, "global_scale")
        layout.prop(operator, "use_scene_unit")

        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")

        layout.prop(operator, "use_mesh_modifiers")

        layout.prop(operator, "write_raw_file")


class SFMESH_PT_export_main(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = ""
    bl_parent_id = "FILE_PT_operator"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "EXPORT_MESH_OT_sfmesh"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "batch_mode")


class SFMESH_PT_export_include(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Include"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "EXPORT_MESH_OT_sfmesh"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "use_selection")


class SFMESH_PT_export_transform(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Transform"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "EXPORT_MESH_OT_sfmesh"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "global_scale")
        layout.prop(operator, "use_scene_unit")

        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")


class SFMESH_PT_export_geometry(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Geometry"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "EXPORT_MESH_OT_sfmesh"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "use_mesh_modifiers")


def menu_export(self, context):
    self.layout.operator(ExportSFMesh.bl_idname, text="SFMesh (.txt)")


classes = (
    ExportSFMesh,
    SFMESH_PT_export_main,
    SFMESH_PT_export_include,
    SFMESH_PT_export_transform,
    SFMESH_PT_export_geometry,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)


if __name__ == "__main__":
    register()
    bpy.ops.export.sfmesh("INVOKE_DEFAULT")
