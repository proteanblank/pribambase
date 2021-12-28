import bpy
import gpu
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.geometry import intersect_point_tri, barycentric_transform
from gpu_extras.batch import batch_for_shader


def _draw_callback_px(self, context):
    if not self.brush:
        return

    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRI_STRIP', {"pos": self.brush})
    shader.bind()
    shader.uniform_float("color", (0.0, 1.0, 0.72, 1))
    batch.draw(shader)


class SB_OT_pencil(bpy.types.Operator):
    bl_description = "..."
    bl_idname = "pribambase.pencil"
    bl_label = "Pencil"
    bl_options = {'REGISTER', 'UNDO'}

    def cast_ray(self, context, event):
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y
        obj = self.obj

        # get the ray from the viewport and mouse
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_target = ray_origin + view_vector

        matrix_inv = obj.matrix_world.inverted()
        ray_origin_obj = matrix_inv @ ray_origin
        ray_target_obj = matrix_inv @ ray_target
        ray_direction_obj = ray_target_obj - ray_origin_obj

        success, location, normal, face_index = obj.ray_cast(ray_origin_obj, ray_direction_obj)
        return success, location, face_index


    @classmethod
    def poll(cls, context):
        return bpy.context.active_object and bpy.context.active_object.type == 'MESH'
    

    def modal(self, context, event:bpy.types.Event):

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}

        elif event.type == 'MOUSEMOVE':
            hit, location, face_index = self.cast_ray(context, event)
            
            if hit:
                mesh = self.obj.data
                for tri in mesh.loop_triangles:
                    # need to use barycentric transform (triangle <-> triangle, no polys)
                    # hence check which triangle we've hit, cuz texture stretch can be different
                    if tri.polygon_index == face_index:
                        verts = [mesh.vertices[v].co for v in tri.vertices]
                        if intersect_point_tri(location, *verts):
                            uvs = [(*mesh.uv_layers.active.data[i].uv, 0) for i in tri.loops]
                            location_uv = Vector(barycentric_transform(location, *verts, *uvs))
                            
                            # pixel corners; 2d vectors, with Z=0 added to transform to 3d later
                            px = (location_uv[0] - location_uv[0] % self.grid[0], location_uv[1] - location_uv[1] % self.grid[1], 0)
                            strip = [px,
                                (px[0], px[1] + self.grid[1], 0),
                                (px[0] + self.grid[0], px[1] + self.grid[1], 0),
                                (px[0] + self.grid[0], px[1], 0), 
                                px]
                            self.brush = [barycentric_transform(p, *uvs, *verts) for p in strip]

                            context.area.tag_redraw()
            else:
                self.brush = None

        elif event.type in ('RIGHTMOUSE', 'ESC'):
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            context.area.tag_redraw()
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


    def invoke(self, context, event):
        self.obj = bpy.context.active_object
        self.obj.data.calc_loop_triangles()
        self.grid = (1/128, 1/128, 0)
        self.brush = None

        # draw handler
        args = (self, context)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(_draw_callback_px, args, 'WINDOW', 'POST_VIEW')

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}