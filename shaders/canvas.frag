#version 430

in vec2 texcoord;

uniform sampler2D brush_tex;
uniform sampler2D can_tex;
uniform float TRAIL_PERSISTENCE;
out vec4 can_out;

vec4 getCan(vec2 p, sampler2D sam) {
    return texture(sam, p);
}

vec4 getBlur(vec2 pos, sampler2D sam) {
    ivec2 imsz = textureSize(sam, 0);
    vec3 off = vec3(1. / vec2(imsz), 0);
    vec2 np = pos + off.zy;
    vec2 sp = pos - off.zy;
    vec2 wp = pos - off.xz;
    vec2 ep = pos + off.xz;
    vec4 nc = getCan(np, sam);
    vec4 sc = getCan(sp, sam);
    vec4 wc = getCan(wp, sam);
    vec4 ec = getCan(ep, sam);
    float K = 0;
    return (getCan(pos, sam) * K + nc + sc + wc + ec) / (4. + K);
}

void main() {
    vec4 brush_color = texture(brush_tex, texcoord);
    vec4 can_color = getBlur(texcoord, can_tex);
    can_out = can_color * TRAIL_PERSISTENCE + (1 - TRAIL_PERSISTENCE) * brush_color;
}
