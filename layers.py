import bpy

from itertools import chain
from typing import Tuple

from .ase import BlendMode


def create_node_helper():
    """Create helper node group. It calculates the mask of the cel, and does gamma correction for mixing later"""        
    tree:bpy.types.ShaderNodeTree = bpy.data.node_groups.new("PribambaseLayersHelper", 'ShaderNodeTree')

    tree.inputs.new('NodeSocketVector', "UV")
    tree.inputs.new('NodeSocketColor', "Color")
    tree.inputs.new('NodeSocketFloat', "Alpha")
    tree.inputs.new('NodeSocketFloat', "Layer Opacity")

    tree.outputs.new('NodeSocketColor', "Color")
    tree.outputs.new('NodeSocketFloat', "Alpha")

    group_in = tree.nodes.new('NodeGroupInput')
    group_in.location = (0, 0)
    group_out = tree.nodes.new('NodeGroupOutput')
    group_out.location = (1200, 0)

    # mask rectangle (0,1)x(0,1) - clear texture stretching outside of the cel
    xyz = tree.nodes.new('ShaderNodeSeparateXYZ')
    xyz.location = (300, 100)

    cmp_x:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    cmp_x.location = (450, 200)
    cmp_y:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    cmp_y.location = (450, 100)
    cmp_x.operation = cmp_y.operation = 'COMPARE'
    cmp_x.inputs[0].default_value = cmp_y.inputs[0].default_value = 0.5
    cmp_x.inputs[1].default_value = cmp_y.inputs[1].default_value = 0.5

    cmp_and:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    cmp_and.location = (600, 100)
    cmp_and.operation = 'MINIMUM'

    tree.links.new(group_in.outputs["UV"], xyz.inputs["Vector"])
    tree.links.new(xyz.outputs["X"], cmp_x.inputs["Value"])
    tree.links.new(xyz.outputs["Y"], cmp_y.inputs["Value"])
    tree.links.new(cmp_x.outputs["Value"], cmp_and.inputs[0])
    tree.links.new(cmp_y.outputs["Value"], cmp_and.inputs[1])

    # mix aplhas
    a_ch:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    a_ch.location = (750, 100)
    a_layer:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    a_layer.location = (900, 100)
    a_ch.operation = a_layer.operation = 'MULTIPLY'

    tree.links.new(cmp_and.outputs["Value"], a_ch.inputs[0])
    tree.links.new(group_in.outputs["Alpha"], a_ch.inputs[1])
    tree.links.new(a_ch.outputs["Value"], a_layer.inputs[0])
    tree.links.new(group_in.outputs["Layer Opacity"], a_layer.inputs[1])
    tree.links.new(a_layer.outputs["Value"], group_out.inputs["Alpha"])

    # correct color gamma so that mix node blending works same as in ase
    # after blending it should be corrected back
    gamma_out = create_gamma_nodes(tree, 300, -100, 1/2.2, group_in.outputs["Color"])
    tree.links.new(gamma_out, group_out.inputs["Color"])


def update_group_outputs(tree:bpy.types.ShaderNodeTree, groups):
    """Create or assure Color and Alpha outputs for the entire sprite and each top-level group"""
    outs = tree.outputs

    print([a for a in chain(("",), groups)])

    # first iteration checks first two outputs being sprite's combined color and alpha
    # after that, extra two per group, same order as the groups
    for i,(name, ) in enumerate(chain([("",)], groups)):
        color_name = f"{name} Color" if name else "Color"
        color_goes = 2 * i # first two are the sprite's color and alpha
        alpha_name = f"{name} Alpha" if name else "Alpha"
        alpha_goes = 2 * i + 1

        color_idx = next((i for i,out in enumerate(outs) if out.name == color_name), None)
        if not color_idx:
            color_idx = len(outs)
            outs.new('NodeSocketColor', color_name)
        outs.move(color_idx, color_goes)
        
        alpha_idx = next((i for i,out in enumerate(outs) if out.name == alpha_name), None)
        if not alpha_idx:
            alpha_idx = len(outs)
            outs.new('NodeSocketFloat', alpha_name)
        outs.move(alpha_idx, alpha_goes)
    
    # at this point, we swapped first `2 + 2*len(groups)` outputs
    # ones remaining are no longer in the sprite and should be removed
    end = 2 + 2 * len(groups)
    for _ in range(end, len(outs)):
        outs.remove(outs[end]) # del is not implemented ( ' _ ' )


def create_layer_image_nodes(tree:bpy.types.ShaderNodeTree, node_x:float, node_y:float, uv_node:bpy.types.ShaderNodeUVMap, \
    x:float, y:float, w:float, h:float, image:bpy.types.Image, opacity:float) \
        -> Tuple[bpy.types.NodeSocketColor, bpy.types.NodeSocketFloat]: # outputs for color and alpha
    """Transform and mask cel image. NOTE this function accepts normalized x/y/w/h/opacity, as in (0.0, 1.0) range"""
    mapping:bpy.types.ShaderNodeMapping = tree.nodes.new('ShaderNodeMapping')
    mapping.vector_type = 'TEXTURE'
    mapping.inputs['Location'].default_value = (x, y, 0.0)
    mapping.inputs['Scale'].default_value = (w, h, 0.0)
    mapping.location = (node_x, node_y)

    image_node:bpy.types.ShaderNodeTexImage = tree.nodes.new('ShaderNodeTexImage')
    image_node.location = (node_x + 200, node_y)
    image_node.image = image

    helper:bpy.types.ShaderNodeGroup = tree.nodes.new('ShaderNodeGroup')
    helper.location = (node_x + 500, node_y)
    helper.node_tree = bpy.data.node_groups["PribambaseLayersHelper"]
    helper.inputs["Layer Opacity"].default_value = opacity

    tree.links.new(uv_node.outputs["UV"], mapping.inputs["Vector"])
    tree.links.new(uv_node.outputs["UV"], helper.inputs["UV"])
    tree.links.new(mapping.outputs["Vector"], image_node.inputs["Vector"])
    tree.links.new(image_node.outputs["Color"], helper.inputs["Color"])
    tree.links.new(image_node.outputs["Alpha"], helper.inputs["Alpha"])

    return (helper.outputs["Color"], helper.outputs["Alpha"])


def create_mix_nodes(tree:bpy.types.ShaderNodeTree, node_x:float, node_y:float, blend_mode:str, \
    color1:bpy.types.NodeSocketColor, alpha1:bpy.types.NodeSocketFloat, \
    color2:bpy.types.NodeSocketColor, alpha2:bpy.types.NodeSocketFloat) \
        -> Tuple[bpy.types.NodeSocketColor, bpy.types.NodeSocketFloat]: # outputs for color and alpha
    """Nodes for mixing RGB components and alpha"""

    mix:bpy.types.ShaderNodeMixRGB = tree.nodes.new('ShaderNodeMixRGB')
    mix.blend_type = blend_mode
    mix.location = (node_x, node_y + 200)

    inv:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    inv.location = (node_x, node_y)
    inv.operation = 'SUBTRACT'
    inv.inputs[0].default_value = 1.0

    mul:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    mul.location = (node_x + 200, node_y)
    mul.operation = 'MULTIPLY'

    add:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    add.location = (node_x + 400, node_y)
    add.operation = 'ADD'
    add.use_clamp = True

    tree.links.new(color1, mix.inputs["Color1"])
    tree.links.new(alpha1, inv.inputs[1])
    tree.links.new(alpha1, add.inputs[1])
    tree.links.new(color2, mix.inputs["Color2"])
    tree.links.new(alpha2, mix.inputs["Fac"])
    tree.links.new(alpha2, mul.inputs[1])
    tree.links.new(inv.outputs["Value"], mul.inputs[0])
    tree.links.new(mul.outputs["Value"], add.inputs[0])

    return (mix.outputs["Color"], add.outputs["Value"])


def create_gamma_nodes(tree:bpy.types.ShaderNodeTree, node_x:float, node_y:float, gamma:float, color_in:bpy.types.NodeSocketColor):
    """Per-component vector exponent"""

    sep:bpy.types.ShaderNodeSeparateRGB = tree.nodes.new('ShaderNodeSeparateRGB')
    sep.location = (node_x, node_y)
    comb:bpy.types.ShaderNodeCombineRGB = tree.nodes.new('ShaderNodeCombineRGB')
    comb.location = (node_x + 300, node_y)
    math_x:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    math_x.location = (node_x + 150, node_y)
    math_y:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    math_y.location = (node_x + 150, node_y - 50)
    math_z:bpy.types.ShaderNodeMath = tree.nodes.new('ShaderNodeMath')
    math_z.location = (node_x + 150, node_y - 100)
    math_x.hide = math_y.hide = math_z.hide = True

    math_x.operation = math_y.operation = math_z.operation = 'POWER'
    math_x.inputs[1].default_value = math_y.inputs[1].default_value = math_z.inputs[1].default_value = gamma

    tree.links.new(color_in, sep.inputs["Image"])
    tree.links.new(sep.outputs["R"], math_x.inputs[0])
    tree.links.new(sep.outputs["G"], math_y.inputs[0])
    tree.links.new(sep.outputs["B"], math_z.inputs[0])
    tree.links.new(math_x.outputs["Value"], comb.inputs["R"])
    tree.links.new(math_y.outputs["Value"], comb.inputs["G"])
    tree.links.new(math_z.outputs["Value"], comb.inputs["B"])

    return comb.outputs["Image"]


def update_layer_group(sprite_width, sprite_height, name, groups, layers):
    if "PribambaseLayersHelper" not in bpy.data.node_groups:
        create_node_helper()

    tree:bpy.types.ShaderNodeTree = None

    if name in bpy.data.node_groups:
        tree = bpy.data.node_groups[name]
        tree.nodes.clear()
    else:
        tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        tree.outputs.new('NodeSocketColor', "Color")
        tree.outputs.new('NodeSocketFloat', "Alpha")

    update_group_outputs(tree, groups)

    group_out = tree.nodes.new('NodeGroupOutput')
    group_out.location = (3250, 0)

    uv:bpy.types.ShaderNodeUVMap = tree.nodes.new('ShaderNodeUVMap')

    # cels
    last_out_color = None
    last_out_alpha = None
    last_group_color = None
    last_group_alpha = None

    # TODO update images and assign them
    for i in range(len(layers)):
        idx, blend, opacity, group, x, y, w, h, name, pixels = layers[i]

        node_y = i * -500
    
        layer_out_color, layer_out_alpha = create_layer_image_nodes(tree, 300, node_y, uv, \
            x / sprite_width, y / sprite_height, w / sprite_width, h / sprite_height, None, opacity / 255)
        
        # top level layer
        if last_out_color:
            mix = BlendMode(blend).toMix()
            last_out_color, last_out_alpha = create_mix_nodes(tree, 1100, node_y + 150, mix, \
                last_out_color, last_out_alpha, layer_out_color, layer_out_alpha)
        else:
            # bottomest layer in the sprite
            last_out_color = layer_out_color
            last_out_alpha = layer_out_alpha

        # mix groups separately
        if group != 0:
            group_end = group != (layers[i + 1][3] if i < len(layers) - 1 else -1)

            if last_group_color:
                mix = BlendMode(blend).toMix()
                last_group_color, last_group_alpha = create_mix_nodes(tree, 1800, node_y + 150, mix, \
                    last_group_color, last_group_alpha, layer_out_color, layer_out_alpha)
            else:
                last_group_color = layer_out_color
                last_group_alpha = layer_out_alpha
            
            if group_end:
                (group_name, ) = groups[group - 1]
                gamma_out = create_gamma_nodes(tree, 2500, group * -200, 2.2, last_group_color)
                tree.links.new(gamma_out, group_out.inputs[f"{group_name} Color"])
                tree.links.new(last_group_alpha, group_out.inputs[f"{group_name} Alpha"])
                last_group_color = None
                last_group_alpha = None

    gamma_out = create_gamma_nodes(tree, 2500, 0, 2.2, last_out_color)
    tree.links.new(gamma_out, group_out.inputs["Color"])
    tree.links.new(last_out_alpha, group_out.inputs["Alpha"])