import bpy
import gpu
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.geometry import intersect_point_tri, barycentric_transform
from gpu_extras.batch import batch_for_shader

from typing import Collection, Generator, Tuple


def line(x1,y1,x2,y2):
    """Bresenham line stepping generator"""
    w = x2 - x1
    w_abs = abs(w)
    h = y2 - y1
    h_abs = abs(h)
    x = x1
    y = y1
    dx = -1 if w < 0 else 1
    dy = -1 if h < 0 else 1

    if abs(w) > abs(h):
        yield x,y

        pk = 2 * h_abs - w_abs
        for i in range(0, w_abs):
            x += dx
            if pk < 0:
                pk += 2 * h_abs
            else:
                y += dy
                pk += 2 * h_abs - 2 * w_abs
            
            yield x, y
    
    else:
        yield x,y

        pk = 2 * w_abs - h_abs

        for i in range(0, h_abs):
            y += dy
            if pk < 0:
                pk += 2 * w_abs
            else:
                x += dx
                pk += 2 * w_abs - 2 * h_abs
            
            yield x, y

def draw_replace(img:bpy.types.Image, dots:Generator[Tuple[int, int], None, None], color:Collection[float]):
    pix = img.pixels
    for x, y in dots:
        addr = 4 * (img.size[0] * y + x)
        pix[addr + 0] = color[0]
        pix[addr + 1] = color[1]
        pix[addr + 2] = color[2]
        pix[addr + 3] = color[3]


def draw_alpha(img:bpy.types.Image, dots:Generator[Tuple[int, int], None, None], color:Collection[float]):
    pix = img.pixels
    for x, y in dots:
        addr = 4 * (img.size[0] * y + x)
        a = color[3]
        da = a * (1 - pix[addr + 3]) # no particular meaning, just repeated a lot
        outa = pix[addr + 3] + da

        pix[addr] = (pix[addr] * a + color[0] * da) / outa
        pix[addr + 1] = (pix[addr + 1] * a + color[1] * da) / outa
        pix[addr + 2] = (pix[addr + 2] * a + color[2] * da) / outa
        pix[addr + 3] = outa


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

    @classmethod
    def poll(cls, context):
        return bpy.context.active_object and bpy.context.active_object.type == 'MESH'
    

    def cast_ray(self, context, event):
        """Raycast mouse position and find uv of the hit; or None"""
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

        if success:
            mesh = self.obj.data
            for tri in mesh.loop_triangles:
                # need to use barycentric transform (triangle <-> triangle, no polys)
                # hence check which triangle we've hit, cuz texture stretch can be different
                if tri.polygon_index == face_index:
                    verts = [mesh.vertices[v].co for v in tri.vertices]
                    if intersect_point_tri(location, *verts):
                        uvs = [(*mesh.uv_layers.active.data[i].uv, 0) for i in tri.loops]
                        location_uv = Vector(barycentric_transform(location, *verts, *uvs))
                        return location_uv, uvs, verts
        return None, None, None


    def modal(self, context, event:bpy.types.Event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        
        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.is_drawing = True
                location_uv, _, __ = self.cast_ray(context, event)
                if location_uv is not None:
                    self.last_px = (int(location_uv.x / self.grid[0]), int(location_uv.y / self.grid[1]))

            elif event.value == 'RELEASE':
                self.is_drawing = False
                img = bpy.data.images['checker128.png'] # FIXME
                img.update()
                img.update_tag()

                # over
                context.window.cursor_modal_restore()
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
                context.area.tag_redraw()
                return {'FINISHED'}

            else:
                self.brush = None
        
        elif event.type == 'MOUSEMOVE':
            location_uv, uvs, verts = self.cast_ray(context, event)
            if location_uv is None:
                self.brush = []
            else:
                # pixel corners; 2d vectors, with Z=0 added to transform to 3d later
                px = (location_uv[0] - location_uv[0] % self.grid[0], location_uv[1] - location_uv[1] % self.grid[1], 0)
                strip = [px,
                    (px[0], px[1] + self.grid[1], 0),
                    (px[0] + self.grid[0], px[1] + self.grid[1], 0),
                    (px[0] + self.grid[0], px[1], 0), 
                    px]
                self.brush = [barycentric_transform(p, *uvs, *verts) for p in strip]

                if self.is_drawing:
                    x = int(px[0] / self.grid[0])
                    y = int(px[1] / self.grid[1])
                    
                    x0, y0 = self.last_px
                    if x0 != x or y0 != y:
                        img = bpy.data.images['checker128.png'] # FIXME
                        col = (1, 0, 0, 1) # FIXME
                        draw_replace(img, line(x0, y0, x, y), col)
                        img.update()
                        self.last_px = x, y
            context.area.tag_redraw()

        return {'RUNNING_MODAL'}


    def invoke(self, context:bpy.types.Context, event):
        self.obj = bpy.context.active_object
        self.obj.data.calc_loop_triangles()
        self.grid = (1/128, 1/128, 0)
        self.brush = None
        self.last_px = (-1, -1)
        self.is_drawing = False

        # draw handler
        args = (self, context)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(_draw_callback_px, args, 'WINDOW', 'POST_VIEW')

        context.window.cursor_modal_set('CROSSHAIR')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}