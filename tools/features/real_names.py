"""Real names: each block's title in the model browser and the Edit view is its real-world counterpart's (helixhelp.com/models,
'based on'), e.g. Deez One Mod -> Boss DS-1 Mod. Line 6 originals, utility blocks and titles that are already real keep theirs.
Off by default: a checkbox on the web page (WEB 'opt-in') and HX_REAL_NAMES for build.py; hxbuild turns it on.

Every model title the M4 code has is in two tables of Entry 0, renamed in place: Table 2's 16-byte short name and each browser
item's 17-byte name. Presets keep model IDs, so a preset is the same with or without the feature."""
import struct

import patch_amp as pa

FLAG = 'HX_REAL_NAMES'
WEB = 'opt-in'

SHORT = 16                                  # Table 2 row bytes 4..20; byte 20 is a 0
BROWSER = 16                                # a browser item's name[0x11] at +0xe, NUL-terminated

# keyed by the stock title (Entry 3 displayName); titles not here stay as they are
BY_TITLE = {
    # amps and preamps
    'WhoWatt 100': 'Hiwatt DR103',
    'US Small Tweed': 'Fender Champ',
    'US Double Vib': 'Twin Reverb Vib',
    'US Double Nrm': 'Twin Reverb Nrm',
    'US Deluxe Vib': 'Deluxe Rvb Vib',
    'US Deluxe Nrm': 'Deluxe Rvb Nrm',
    'Tweed Blues Brt': 'Bassman Brt',
    'Tweed Blues Nrm': 'Bassman Nrm',
    'Stone Age 185': 'Gibson EH-185',
    'Soup Pro': 'Supro S6616',
    'Solo Lead OD': 'SLO-100 OD',
    'Solo Lead Clean': 'SLO-100 Clean',
    'Solo Lead Crunch': 'SLO-100 Crunch',
    'PV Panama': 'Peavey 5150',
    'Mandarin 80': 'Orange OR80',
    'Mail Order Twin': 'Silvertone 1484',
    'Jazz Rivet 120': 'Roland JC-120',
    'Interstate Zed': 'Dr Z Route 66',
    'German Ubersonic': 'Uberschall',
    'German Mahadeva': 'Bogner Shiva',
    'G Cougar 800': 'GK 800RB',
    'Essex A30': 'Vox AC-30 TB',
    'Essex A15': 'Vox AC-15',
    'Divided Duo': 'Div13 JRT 9/15',
    'Cali Rectifire': 'Mesa Rectifier',
    'Cali Bass': 'Mesa M9 Carbine',
    'Cali 400 Ch1': 'Mesa 400+ Ch1',
    'Cali 400 Ch2': 'Mesa 400+ Ch2',
    'Brit Plexi Brt': 'Super Lead Brt',
    'Brit Plexi Jump': 'Super Lead Jump',
    'Brit Plexi Nrm': 'Super Lead Nrm',
    'Brit P75 Brt': 'Park 75 Brt',
    'Brit P75 Nrm': 'Park 75 Nrm',
    'Brit J45 Brt': 'JTM-45 Brt',
    'Brit J45 Nrm': 'JTM-45 Nrm',
    'Brit 2204': 'JCM800 2204',
    'Brit 2203': 'JCM800 2203',
    'ANGL Meteor': 'ENGL Fireball',
    'A30 Fawn Brt': 'AC-30 Fawn Brt',
    'A30 Fawn Nrm': 'AC-30 Fawn Nrm',
    'Matchstick Ch1': 'Matchless Ch1',
    'Matchstick Ch2': 'Matchless Ch2',
    'Matchstick Jump': 'Matchless Jump',
    'Cali IV Rhythm 1': 'Mark IV Rhythm 1',
    'Cali IV Rhythm 2': 'Mark IV Rhythm 2',
    'Cali IV Lead': 'Mark IV Lead',
    'Archetype Lead': 'PRS Archon Lead',
    'Archetype Clean': 'PRS Archon Clean',
    'Del Sol 300': 'Sunn Coliseum',
    'Woody Blue': 'Acoustic 360',
    'Busy One Ch1': 'Pearce BC-1 Ch1',
    'Busy One Ch2': 'Pearce BC-1 Ch2',
    'Busy One Jump': 'Pearce BC-1 Jump',
    'Derailed Ingrid': 'Trainwreck Exp',
    'Voltage Queen': 'Electro King',
    'Brit Trem Brt': 'Plexi Trem Brt',
    'Brit Trem Jump': 'Plexi Trem Jump',
    'Brit Trem Nrm': 'Plexi Trem Nrm',
    'Agua 51': 'Aguilar DB751',
    'Agua Sledge': 'Tone Hammer',
    'Placater Dirty': 'BE-100 Dirty',
    'Placater Clean': 'BE-100 Clean',
    'Cali Texas Ch1': 'Lonestar Ch1',
    'Cali Texas Ch2': 'Lonestar Ch2',
    'GrammaticoLG Brt': 'LaGrange Brt',
    'GrammaticoLG Jmp': 'LaGrange Jump',
    'GrammaticoLG Nrm': 'LaGrange Nrm',
    'Fullerton Brt': 'Tweed Deluxe Brt',
    'Fullerton Jump': 'Tweed Deluxe Jmp',
    'Fullerton Nrm': 'Tweed Deluxe Nrm',
    'US Princess': 'Fender Princeton',
    'Das Benzin Lead': 'Diezel VH4 Lead',
    'Das Benzin Mega': 'Diezel VH4 Mega',
    'Mandarin Rocker': 'Rockerverb 100',
    'Moo)))n Nrm': 'Model T Nrm',
    'Moo)))n Jump': 'Model T Jump',
    'Moo)))n Brt': 'Model T Brt',
    'PV Vitriol Lead': 'Invective Lead',
    'PV VitriolCrunch': 'Invective Crunch',
    'PV Vitriol Clean': 'Invective Clean',
    'US Dripman Norm': 'SF Bassman Nrm',
    'Mandarin Bass 20': 'Orange AD200',          # "Mandarin Bass 200" cut to the short name's 16 bytes
    'US Super Norm': 'Super Reverb Nrm',
    'US Super Vib': 'Super Reverb Vib',
    'German Xtra Red': 'Ecstasy Red',
    'German Xtra Blue': 'Ecstasy Blue',
    'EV Panama Red': 'EVH 5150III Red',
    'EV Panama Blue': 'EVH 5150III Blue',

    # distortion
    'Valve Driver': 'Tube Driver',
    'Hedgehog D9': 'Maxon SD9',
    'Industrial Fuzz': 'Fuzz Factory',
    'Triangle Fuzz': 'Triangle Muff',
    'Minotaur': 'Klon Centaur',
    'Compulsive Drive': 'Fulltone OCD',
    'Top Secret OD': 'DOD OD-250',
    'Vermin Dist': 'Pro Co RAT',
    'Arbitrator Fuzz': 'Fuzz Face',
    'Tycoctavia Fuzz': 'Tyco Octavia',
    'Scream 808': 'Ibanez TS808',
    'KWB': 'Benadrian KWB',
    'Teemah!': 'Timmy Overdrive',
    'Wringer': 'Garbage FZ-2',
    'Wringer Fuzz': 'Garbage FZ-2',
    'Stupor OD': 'Boss SD-1',
    'Obsidian 7000': 'Darkglass B7K',
    'Clawthorn Drive': 'Battering Ram',
    'Kinky Boost': 'Xotic EP Booster',
    'Jet Fuzz': 'Jet Phaser AP-7',
    'Octave Fuzz': 'Tyco Octavia',
    'Screamer': 'Tube Screamer',
    'Buzz Saw': 'Maestro FZ-1',
    'Classic Dist': 'Pro Co RAT',
    'Colordrive': 'Colorsound OD',
    'Facial Fuzz': 'Fuzz Face',
    'Fuzz Pi': 'Big Muff Pi',
    'Heavy Dist': 'Boss Metal Zone',
    'Jumbo Fuzz': 'Tone Bender',
    'Overdrive': 'DOD OD-250',
    'Tube Drive': 'Tube Driver',
    'Deranged Master': 'Rangemaster',
    'Deez One Vintage': 'Boss DS-1 MIJ',
    'Deez One Mod': 'Boss DS-1 Mod',
    'Dhyana Drive': 'Hermida Zendrive',
    'ZeroAmp Bass DI': 'SansAmp Bass DI',
    'Tone Sovereign': 'King of Tone',
    'Heir Apparent': 'Prince of Tone',
    'Alpaca Rouge': 'Red Llama Mod',
    'Legendary Drive': 'Carvin VLD1',
    'Bighorn Fuzz': "Ram's Head Muff",
    'Swedish Chainsaw': 'Boss HM-2',
    'Horizon Drive': 'Precision Drive',
    'Ballistic Fuzz': 'Euthymia ICBM',
    'Pocket Fuzz': 'Jordan Boss Tone',
    'Ratatouille Dist': "Pro Co RAT '84",
    'Killer Z': 'Boss MT-2',
    'Bronze Master': 'Bass Brassmaster',
    'Vital Dist': 'EQD Life Dist',
    'Vital Boost': 'EQD Life Boost',
    'Pillars': 'EQD Plumes',
    'Dark Dove Fuzz': 'Russian Big Muff',
    'Prize Drive': 'Nobels ODR-1',
    'Regal Bass DI': 'Noble Bass DI',

    # dynamics
    'LA Studio Comp': 'Teletronix LA-2A',
    'Tube Comp': 'Teletronix LA-2A',
    'Red Squeeze': 'MXR Dyna Comp',
    'Red Comp': 'MXR Dyna Comp',
    'Kinky Comp': 'Xotic SP Comp',
    'Rochester Comp': 'Ashly CLX-52',
    'Blue Comp': 'Boss CS-1',
    'Blue Comp Treb': 'Boss CS-1 Treble',
    'Horizon Gate': 'Precision Gate',

    # modulation
    '60s Bias Trem': 'Vox AC-15 Trem',
    'Bias Tremolo': 'Vox AC-15 Trem',
    'Ubiquitous Vibe': 'Shin-ei Uni-Vibe',
    'U-Vibe': 'Uni-Vibe',
    'Script Mod Phase': 'Script Phase 90',
    'Script Phase': 'MXR Phase 90',
    'Courtesan Flange': 'EHX Mistress',
    'Gray Flanger': 'MXR 117 Flanger',
    'AC Flanger': 'MXR Flanger',
    'Harmonic Flanger': 'A/DA Flanger',
    '80A Flanger': 'A/DA Flanger',
    '70s Chorus': 'Boss CE-1',
    'Analog Chorus': 'Boss CE-1',
    'Bubble Vibrato': 'Boss VB-2',
    'Pitch Vibrato': 'Boss VB-2',
    'Optical Trem': 'Fender Opto Trem',
    'Tremolo': 'Boss PN-2',
    'Tremolo/Autopan': 'Boss PN-2',
    'PlastiChorus': 'Arion SCH-Z',
    'Bleat Chop Trem': 'Goatkeeper',
    'Pebble Phaser': 'EHX Small Stone',
    '122 Rotary': 'Leslie 122',
    '145 Rotary': 'Leslie 145',
    'Rotary Drum/Horn': 'Leslie 145',
    'Vibe Rotary': 'Fender Vibratone',
    'Rotary Drum': 'Fender Vibratone',
    'Trinity Chorus': 'TriStereo Chorus',
    'Tri Chorus': 'TriStereo Chorus',
    'Dual Phaser': 'Mu-Tron Bi-Phase',
    'Panned Phaser': 'Ibanez FlyingPan',
    'Dimension': 'Roland Dimension',
    'Triple Rotary': 'Roland RA-200',

    # delay
    'Ducked Delay': 'TC 2290',
    'Adriatic Delay': 'DM-2 Adrian Mod',
    'Bucket Brigade': 'Boss DM-2',
    'Analog Echo': 'Boss DM-2',
    'Elephant Man': 'EHX Memory Man',
    'Analog w/Mod': 'EHX Memory Man',
    'Transistor Tape': 'Echoplex EP-3',
    'Tape Echo': 'Echoplex EP-3',
    'Tube Echo': 'Echoplex EP-1',
    'Cosmos Echo': 'Roland RE-201',
    'Multi-Head': 'Roland RE-101',
    'Echo Platter': 'Binson EchoRec',

    # wah
    'Teardrop 310': 'Dunlop 310',
    'Teardrop Bass Q': 'Dunlop 105Q',
    'UK Wah 846': 'Vox V846',
    'Chrome': 'Vox V847',
    'Chrome Custom': 'Vox V847 Mod',
    'Colorful': 'Colorsound Wah',
    'Conductor': 'Boomerang Wah',
    'Fassel': 'Cry Baby Super',
    'Throaty': 'RMC Real McCoy 1',
    'Weeper': 'Arbiter Cry Baby',

    # pitch, filter, EQ, synth
    'Twin Harmony': 'Eventide H3000',
    'Pitch Wham': 'DigiTech Whammy',
    'Boctaver': 'Boss OC-2',
    'Mutant Filter': 'Mu-Tron III',
    'Mystery Filter': 'Korg A3',
    'Asheville Pattrn': 'Moog MF Murf',
    '10 Band Graphic': 'MXR 10-Band EQ',
    'Cali Q Graphic': 'Mark IV Graphic',
    'Acoustic Sim': 'Boss AC-2',
    'Synth String': 'Roland GR-700',
    'Attack Synth': 'Korg X-911',

    # cabs
    '4x12 Mandarin': '4x12 Orange EM',
    '4x12 Mandarin EM': '4x12 Orange EM',
    '2x12 Mandarin': '2x12 Orange V30',
    '4x12 Uber T75': '4x12 Bogner T75',
    '4x12 Uber V30': '4x12 Bogner V30',
    '2x12 Jazz Rivet': '2x12 JC-120',
    '1x12 Grammatico': '1x12 LaGrange',
    '2x12 Mail C12Q': '2x12 Silvertone',
    '4x12 Cali V30': '4x12 Mesa V30',
    '4X12 Cali V30': '4x12 Mesa V30',
    '4x12 Brit V30': '4x12 1960AV V30',
    '4x12 MOON T75': '4x12 Sunn T75',
    '4x12 XXL V30': '4x12 ENGL V30',
    '4x12 Blckbck H30': '4x12 Park H30',
    '4x12 Blackback30': '4x12 Park H30',
    '2x12 Blue Bell': '2x12 AC-30 Blue',
    '1x12 Blue Bell': '1x12 AC-15 Blue',
    '2x12 Silver Bell': '2x12 AC30 Silver',
    '2x12 Double C12N': '2x12 Twin C12N',
    '1x12 US Deluxe': '1x12 Deluxe Rvb',
    '4x10 Tweed P10R': '4x10 Bassman',
    '2x15 US Dripman': '2x15 Bassman',
    '8x10 SV Beast': '8x10 Ampeg SVT',
    '1x10 US Princess': '1x10 Princeton',
    '1x12 US Princess': '1x12 Princeton',
    '2x15 Brute': '2x15 Mesa EV',
    '1x15 Tuck n\' Go': '1x15 Ampeg B15',
    '4x10 Rhino': '4x10 Ampeg HLF',
    '4x10 Garden': '4x10 Eden D410',
    '1x12 Cali EXT': '1x12 Mesa Ext',
    '1x12 Cali IV': '1x12 Mesa Mk IV',
    '6x10 Cali Power': '6x10 Mesa PwrHse',
    '1x12 Epicenter': '1x12 Epifani',
    '2x12 Match G25': '2x12 DC-30 G25',
    '2x12 Match H30': '2x12 DC-30 H30',
    '2x12 Interstate': '2x12 Dr Z V30',
    'Soup Pro Ellipse': '1x6x9 Supro',
    '1x12 Fullerton': '1x12 5C3 Deluxe',
    '1x8 Small Tweed': '1x8 Fender Champ',
    '4x12 WhoWatt 100': '4x12 Hiwatt',
    '4x10 US Super': '4x10 Super Rvb',
    '4x12 SoloLead EM': '4x12 Soldano',
    '1x12 Celest 12H': '1x12 Div13 H30',
    '1x12 Field Coil': '1x12 EH-185',
    '1x12 Lead 80': '1x12 Shiva CL80',
    '1x18 Woody Blue': '1x18 Acoustic360',
}

# stock Legacy cabs whose title is another cab's ("4x12 SoloLead EM"): named by model
BY_MODEL = {
    'HD2_Cab1x12CaliExt': '1x12 Mesa Ext',
    'HD2_Cab1x12CaliIV': '1x12 Mesa Mk IV',
    'HD2_Cab1x12DelSol': '1x12 Coliseum',
    'HD2_Cab1x18DelSol': '1x18 Coliseum',
}


def real_name(model, title):
    """The new title of a model (its internal name and stock title)."""
    return BY_MODEL.get(model) or BY_TITLE.get(title, title)


def strings(e3):
    """Entry 3's string table: a model's name index into it gives its internal name."""
    str_off = struct.unpack_from('<I', e3, 12)[0]
    nstr = struct.unpack_from('<I', e3, str_off)[0]
    base = str_off + 8 + 12 * nstr
    out = []
    for i in range(nstr):
        roff, _, ln = struct.unpack_from('<3I', e3, str_off + 8 + 12 * i)
        out.append(e3[base + roff: base + roff + ln].decode('latin1'))
    return out


def renames(p):
    """{name index: new title} of every model Table 2 lists whose title changes."""
    A = pa.e0_device(p.segs)
    names = strings(p.entry(3).read(0, len(p.entry(3).data)))
    rows = p.u32(A.TAB2_BASE_PTR)
    _, n = pa._decode_thumb_movw(p.read(A.TAB2_CNT_INSN, 4))
    out = {}
    for i in range(n):
        row = p.read(rows + 44 * i, 44)
        ni = struct.unpack_from('<I', row)[0]
        title = row[4:4 + SHORT].split(b'\0')[0].decode('latin1')
        new = real_name(names[ni], title)
        if new != title:
            out[ni] = (rows + 44 * i, new)
    return out


def apply(p):
    A = pa.e0_device(p.segs)
    found = renames(p)
    for ni, (row, new) in found.items():
        p.put(row + 4, new.encode('ascii').ljust(SHORT, b'\0'), f'the short name of model {ni}')
    for idx in range(pa.E0_BLIST_SLOTS):
        items, count = p.u32(A.BLIST_PTR_TAB + 4 * idx), p.u32(A.BLIST_CNT_TAB + 4 * idx)
        for k in range(count if items else 0):
            ni = struct.unpack_from('<I', p.read(items + 48 * k + 4, 4))[0]
            if ni in found:
                p.put(items + 48 * k + 14, found[ni][1].encode('ascii').ljust(BROWSER + 1, b'\0'), f'a browser item of model {ni}')
