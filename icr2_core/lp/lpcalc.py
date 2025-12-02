import math

def get_trk_sect_type(trk, dlong):
    """ Given a DLONG and a TRK object, return 1 for straight and 2 for curve.
    """
    for i in range(0, trk.numSections - 1):
        if trk.sects[i].dlong <= dlong < trk.sects[i+1].dlong:
            return trk.sects[i].type
    if trk.sects[trk.numSections - 1].dlong <= dlong:
        return trk.sects[trk.numSections - 1].type

def get_trk_sect_id(trk, dlong):
    """ Given a DLONG and a TRK object, return the Section number.
    """
    for i in range(0, trk.numSections - 1):
        if trk.sects[i].dlong <= dlong < trk.sects[i+1].dlong:
            return i
    if trk.sects[trk.numSections - 1].dlong <= dlong:
        return trk.numSections - 1

def get_trk_sect_radius(trk, sect_id):
    """ Calculate radius based on heading and length
    """
    a0 = int(trk.sects[sect_id].heading)
    a1 = int(trk.sects[sect_id + 1].heading)
    x = (a1 - a0)/2147483648

    if x > 1:
        x -= 2
    elif x < -1:
        x += 2

    r = trk.sects[sect_id].length / (x * math.pi)
    return r

def get_fake_radius1(g31, c31, f30, c30):
    r = (g31 * math.tan((c31 - f30)/g31) + f30 - c30) / math.tan((c31 - f30)/g31)
    return r

def get_fake_radius2(g73, f74, c74, c75):
    r = (g73 * math.tan((f74 - c74)/g73) + c75 - f74) / math.tan((f74 - c74)/g73)
    return r

def get_fake_radius3(dlongc, dlong0, r0, dlong1, r1):
    r = (math.sin((dlongc - dlong0) / r0) * r0 \
    + math.sin((dlong1 - dlongc) / r1) * r1) \
    / (math.sin((dlongc - dlong0) / r0)  \
    + math.sin((dlong1 - dlongc) / r1))
    return r
