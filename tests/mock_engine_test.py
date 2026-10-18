# -*- coding: utf-8 -*-
# Python 2.7 smoke test with fake engine modules.
import sys, types, math, random
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

# ---------------- Math
class Vector3(object):
    def __init__(self, *a):
        if len(a) == 1:
            a = tuple(a[0])
        if not a:
            a = (0, 0, 0)
        self.x, self.y, self.z = float(a[0]), float(a[1]), float(a[2])
    def __iter__(self): return iter((self.x, self.y, self.z))
    def __getitem__(self, i): return (self.x, self.y, self.z)[i]
    def __add__(s, o): o = Vector3(o); return Vector3(s.x+o.x, s.y+o.y, s.z+o.z)
    def __sub__(s, o): o = Vector3(o); return Vector3(s.x-o.x, s.y-o.y, s.z-o.z)
    def __mul__(s, k):
        assert isinstance(k, (int, float)), 'vector*vector used!'
        return Vector3(s.x*k, s.y*k, s.z*k)
    __rmul__ = __mul__
    def __neg__(s): return s * -1.0
    @property
    def length(s): return math.sqrt(s.x*s.x+s.y*s.y+s.z*s.z)
    def normalise(s):
        l = s.length or 1.0
        s.x /= l; s.y /= l; s.z /= l
    def distTo(s, o): return (s - o).length
    def __repr__(s): return 'V(%.2f,%.2f,%.2f)' % (s.x, s.y, s.z)

def mmul(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

class Matrix(object):
    def __init__(self, other=None):
        self.m = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        if other is not None:
            self.m = [row[:] for row in other.m]
    def set(self, o): self.m = [row[:] for row in o.m]
    def setIdentity(self): self.__init__()
    def setTranslate(self, v):
        self.setIdentity(); self.translation = v
    @property
    def translation(self): return Vector3(self.m[3][0], self.m[3][1], self.m[3][2])
    @translation.setter
    def translation(self, v):
        v = Vector3(v); self.m[3][0], self.m[3][1], self.m[3][2] = v.x, v.y, v.z
    def _rot(self, axis, a):
        c, s = math.cos(a), math.sin(a)
        r = Matrix()
        if axis == 'y': r.m[0][0], r.m[0][2], r.m[2][0], r.m[2][2] = c, -s, s, c
        if axis == 'x': r.m[1][1], r.m[1][2], r.m[2][1], r.m[2][2] = c, s, -s, c
        if axis == 'z': r.m[0][0], r.m[0][1], r.m[1][0], r.m[1][1] = c, s, -s, c
        return r
    def setRotateY(self, a): self.m = self._rot('y', a).m
    def setRotateX(self, a): self.m = self._rot('x', a).m
    def setRotateYPR(self, ypr):
        y, p, r = ypr
        self.m = mmul(mmul(self._rot('z', r).m, self._rot('x', p).m), self._rot('y', y).m)
    def preMultiply(self, o): self.m = mmul(o.m, self.m)
    def postMultiply(self, o): self.m = mmul(self.m, o.m)
    def applyPoint(self, p):
        p = Vector3(p); m = self.m
        return Vector3(*[p.x*m[0][j]+p.y*m[1][j]+p.z*m[2][j]+m[3][j] for j in range(3)])
    def applyVector(self, p):
        p = Vector3(p); m = self.m
        return Vector3(*[p.x*m[0][j]+p.y*m[1][j]+p.z*m[2][j] for j in range(3)])
    def applyToAxis(self, i): return Vector3(self.m[i][0], self.m[i][1], self.m[i][2])
    def invert(self):
        # rigid inverse
        r = [[self.m[j][i] for j in range(3)] for i in range(3)]
        t = self.translation
        n = Matrix()
        for i in range(3):
            for j in range(3):
                n.m[i][j] = r[i][j]
        nt = Vector3(*[-(t.x*r[0][j]+t.y*r[1][j]+t.z*r[2][j]) for j in range(3)])
        n.translation = nt
        self.m = n.m
    def lookAt(self, pos, d, up):
        z = Vector3(d); z.normalise()
        up = Vector3(up)
        x = Vector3(up.y*z.z-up.z*z.y, up.z*z.x-up.x*z.z, up.x*z.y-up.y*z.x); x.normalise()
        y = Vector3(z.y*x.z-z.z*x.y, z.z*x.x-z.x*x.z, z.x*x.y-z.y*x.x)
        w = Matrix()
        for i, v in enumerate((x, y, z)):
            w.m[i][0], w.m[i][1], w.m[i][2] = v.x, v.y, v.z
        w.translation = pos
        w.invert()
        self.m = w.m

MathMod = types.ModuleType('Math'); MathMod.Vector3 = Vector3; MathMod.Matrix = Matrix
sys.modules['Math'] = MathMod

# ---------------- BigWorld
BW = types.ModuleType('BigWorld')
_t = [0.0]
_callbacks = []
BW.time = lambda: _t[0]
def callback(d, f):
    _callbacks.append(f); return len(_callbacks)
BW.callback = callback
BW.cancelCallback = lambda i: None
class Res(object):
    def __init__(s, p): s.closestPoint = p; s.matKind = 3
def collideSegment(sid, a, b, flags):
    # flat ground at y=10, wall at z=400
    a, b = Vector3(a), Vector3(b)
    if (a.y - 10) * (b.y - 10) <= 0 and a.y != b.y:
        t = (a.y - 10) / (a.y - b.y)
        return Res(a + (b - a) * t)
    if (a.z - 400) * (b.z - 400) < 0:
        t = (a.z - 400) / (a.z - b.z)
        return Res(a + (b - a) * t)
    return None
BW.wg_collideSegment = collideSegment
class Space(object): id = 7
BW.createSpace = lambda: Space()
BW.clearAllSpaces = lambda: None
BW.worldDrawEnabled = lambda v: None
BW.addSpaceGeometryMapping = lambda *a: 1
BW.spaceLoadStatus = lambda: 1.0
BW.uniprofSceneStart = lambda: None
class Cam(object):
    def __init__(s): s.matrix = Matrix()
    def set(s, m): s.matrix = Matrix(m)
_cam = [None]
BW.FreeCamera = Cam
def camera(c=None):
    if c is not None: _cam[0] = c
    return _cam[0]
BW.camera = camera
class Proj(object): fov = 1.2
BW.projection = lambda: Proj
class Node(object):
    def __init__(s, model, name): s.model, s.name = model, name; s.local = None; s.localMatrix = None
class Model(object):
    def __init__(s, *a): s.matrix = None; s.root = s; s.visible = True
    def node(s, name):
        if name in ('hull', 'chassis', 'turret', 'gun', 'HP_gunFire', 'HP_turretJoint', 'Gun'):
            m = Matrix(s.matrix) if s.matrix is not None else Matrix()
            m.translation = m.translation + Vector3(0, 2.0, 0)
            return m
        return None
    def setupFashions(s, f): pass
    def addMotor(s, m): pass
    def attach(s, a): pass
class MatProv(Node):
    pass
_entities = {}
class Ent(object):
    def __init__(s, pos): s.position = pos; s.model = None
    def addModel(s, m): pass
    def delModel(s, m): pass
def createEntity(cls, sid, vid, pos, d, props):
    i = len(_entities) + 1; _entities[i] = Ent(pos); return i
BW.createEntity = createEntity
BW.entity = lambda i: _entities[i]
BW.entities = _entities
BW.destroyEntity = lambda i: _entities.pop(i, None)
BW.player = lambda: None
class Refs(dict):
    failedIDs = set()
def loadResourceListBG(res, cb):
    r = Refs(); r['alive'] = Model(); r['dead'] = Model()
    _callbacks.append(lambda: cb(r))
BW.loadResourceListBG = loadResourceListBG
BW.WGVehicleFashion = BW.WGBaseFashion = object
BW.Model = Model
class Servo(object):
    def __init__(s, m): s.signal = m
BW.Servo = Servo
BW.addModel = lambda m, s: None
_keys = set()
BW.isKeyDown = lambda k: k in _keys
BW.quit = lambda: None
sys.modules['BigWorld'] = BW

# ---------------- GUI / Keys
G = types.ModuleType('GUI')
class T(object):
    def __init__(s, t=''): s.text = t
G.Text = T
G.Attachment = T
class Simple(object):
    class eHAnchor: LEFT, CENTER, RIGHT = 0, 1, 2
    class eVAnchor: TOP, CENTER, BOTTOM = 0, 1, 2
    class eFilterType: LINEAR = 1
G.Simple = Simple
G.addRoot = lambda t: None
G.screenResolution = lambda: (1920, 1080)
G.mcursor = lambda: T()
sys.modules['GUI'] = G
K = types.ModuleType('Keys')
for i, n in enumerate('1 2 3 4 W A S D F1 F5 ESCAPE LSHIFT LEFTMOUSE RIGHTMOUSE RETURN NUMPADENTER'.split()):
    setattr(K, 'KEY_' + n, i + 1)
sys.modules['Keys'] = K

# ---------------- game data
class HT(object):
    bbox = (Vector3(-1.5, 0, -3), Vector3(1.5, 1.2, 3))
    def isBspModelLoaded(s): return True
    def worldHitTest(s, a, b, wm):
        # sphere r=2 at part translation
        c = wm.translation + Vector3(0, 1, 0)
        d = b - a; L = d.length; d.normalise()
        t = ((c - a).x*d.x + (c - a).y*d.y + (c - a).z*d.z)
        if t < 0 or t > L: return None
        if (a + d * t - c).length < 2.0: return [(t, Vector3(0, 0, 1), 0.8, 1)]
        return None
class Mat(object): armor = 80.0
class Part(object):
    def __init__(s): s.hitTesterManager = types.ModuleType('h'); s.hitTesterManager.modelHitTester = HT(); s.materials = {1: Mat()}
class Desc(object):
    def __init__(s):
        s.type = types.ModuleType('t'); s.type.speedLimits = (12.0, 5.0); s.type.shortUserString = 'Тигр'
        s.maxHealth = 1500
        s.chassis = Part(); s.chassis.rotationSpeed = 0.5; s.chassis.hullPosition = Vector3(0, 0.5, 0); s.chassis.splineDesc = None; s.chassis.topRightCarryingPoint = (1.4, 2.6)
        s.hull = Part(); s.hull.turretPositions = [Vector3(0, 1.5, 0)]; s.hull.turretPitches = [0.0]
        s.hull.primaryArmor = (100.0, 80.0, 80.0); s.turret = Part(); s.turret.primaryArmor = (100.0, 80.0, 80.0); s.turret.rotationSpeed = 0.4; s.turret.gunPosition = Vector3(0, 0.5, 1)
        s.gun = Part(); s.gun.rotationSpeed = 0.5; s.gun.pitchLimits = {'absolute': (-0.3, 0.15)}; s.gun.reloadTime = 2.0
        s.gun.aimingTime = 2.0; s.gun.shotDispersionAngle = 0.003; s.gun.turretYawLimits = None; s.gun.effects = None
        sh = types.ModuleType('s'); sh.armorDamage = (240.0, 240.0); sh.caliber = 88.0; sh.kind = 'ARMOR_PIERCING'; sh.effectsIndex = 0
        s.gun.maxAmmo = 60
        s.shot = types.ModuleType('sh'); s.shot.speed = 800.0; s.shot.gravity = 9.8; s.shot.maxDistance = 1000.0; s.shot.piercingPower = (150.0, 120.0); s.shot.shell = sh
        s.gun.shots = [s.shot, s.shot]
items = types.ModuleType('items'); vehicles = types.ModuleType('items.vehicles')
vehicles.g_list = types.ModuleType('gl'); vehicles.g_list.getIDsByName = lambda n: (0, 1)
vehicles.VehicleDescr = lambda typeID=None: Desc()
vehicles.g_cache = types.ModuleType('gc'); vehicles.g_cache.shotEffects = [{}]
items.vehicles = vehicles
sys.modules['items'] = items; sys.modules['items.vehicles'] = vehicles
vs = types.ModuleType('vehicle_systems'); ma = types.ModuleType('vehicle_systems.model_assembler')
class Asm(object): name = ''
ma.prepareCompoundAssembler = lambda *a, **k: Asm()
ma.setupTracksFashion = lambda *a: None
ts = types.ModuleType('vehicle_systems.tankStructure')
ts.ModelsSetParams = lambda *a: a
vs.model_assembler = ma
sys.modules['vehicle_systems'] = vs; sys.modules['vehicle_systems.model_assembler'] = ma; sys.modules['vehicle_systems.tankStructure'] = ts
at = types.ModuleType('ArenaType')
class AT(object):
    geometryName = '05_prohorovka'; gameplayName = 'ctf'
    boundingBox = ((-500, -500), (500, 500))
    teamSpawnPoints = ([(0, -300)], [(0, 300), (100, 300)])
    teamBasePositions = None
at.g_cache = {1: AT()}
sys.modules['ArenaType'] = at
helpers = types.ModuleType('helpers'); om = types.ModuleType('helpers.OfflineMode'); helpers.OfflineMode = om
sys.modules['helpers'] = helpers; sys.modules['helpers.OfflineMode'] = om
gm = types.ModuleType('game'); gm.handleKeyEvent = lambda e: False; gm.handleMouseEvent = lambda e: False
sys.modules['game'] = gm

sys.argv = ['WorldOfTanks.exe']
open('sandbox_launch.txt','w').write('map=05_prohorovka bots=4 allies=1\r\n')
import mod_sandbox as M
V3n = M.V3
M.init()
assert om.onStartup() is True

def pump(n, dt=1/60.0):
    for _ in range(n):
        _t[0] += dt
        cbs = list(_callbacks); del _callbacks[:]
        for c in cbs: c()

pump(5)
g = M.g_game
print 'state', g.state, 'tanks', len(g.tanks), [t.loaded for t in g.tanks]
class Ev(object):
    def __init__(s, k, down=True): s.key = k; s._d = down; s.dx = 30; s.dy = 5; s.dz = 0
    def isKeyDown(s): return s._d
    def isRepeatedEvent(s): return False
gm.handleMouseEvent(Ev(0))
_keys.add(K.KEY_W)
pump(120)
print 'player pos', g.player.pos, 'speed', round(g.player.speed, 2), 'turretYaw', round(g.player.turretYaw, 3)
gm.handleKeyEvent(Ev(K.KEY_LEFTMOUSE))
pump(600)
t = g.tanks[2]
print 'hitTest', t.hitTest(t.pos + V3n(0, 1.0, -50), t.pos + V3n(0, 1.0, 50)), t.hitTest(t.pos + V3n(-50, 2.2, 0), t.pos + V3n(50, 2.2, 0))
print 'shells', len(g.shells), 'hp', [int(t.hp) for t in g.tanks]
gm.handleKeyEvent(Ev(K.KEY_LSHIFT)); pump(30)
gm.handleKeyEvent(Ev(K.KEY_F5)); pump(30)
p = g.player; e = g.tanks[1]
e.pos = p.pos + V3n(0, 0, 60); e.matrix.translation = e.pos
hits = 0
for i in range(10):
    p.reloadLeft = 0; p.turretYaw = 0; p.gunPitch = 0
    pump(1)
    p.reloadLeft = 0
    p.shoot(); pump(30)
print 'enemy hp after 10 shots', int(e.hp), 'alive', e.alive, 'ammo', p.ammo
gm.handleKeyEvent(Ev(K.KEY_2)); pump(2); print 'shot idx', p.shotIdx
p.hp = 500; gm.handleKeyEvent(Ev(K.KEY_4)); pump(2); print 'hp after repair', p.hp, p.repairKits
print 'hud', repr(g.gui['hud'].text[:200])
print 'after restart', len(g.tanks), g.state
for t in g.tanks[1:]:
    t.applyHit(99999)
pump(5)
print 'state after kills', g.state
print 'msgs', [m[0] for m in g.messages]
print 'OK'
