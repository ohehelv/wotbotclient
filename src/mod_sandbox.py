# -*- coding: utf-8 -*-
# WoT Sandbox: offline battle against simple bots on a real map.
# Launch: win64\WorldOfTanks.exe sandbox map=05_prohorovka tank=germany:G04_PzVI_Tiger_I bots=6
# Works only when 'sandbox' is on the command line; otherwise the mod does nothing.
from __future__ import absolute_import, division
import sys
import math
import random
import traceback

import BigWorld
import Math
import GUI
import Keys

VERSION = '0.5'
_TAG = '[SANDBOX]'

DEFAULTS = {
    'map': '05_prohorovka',
    'tank': 'germany:G04_PzVI_Tiger_I',
    'bots': '6',
    'allies': '0',
    'difficulty': '1.0',
    'mode': 'battle',
    'dmg': '2.0',
    'pen': '0.95',
    'repairs': '3',
    'repairhp': '0.4',
    'tracks': '1',
}
BOT_POOL = [
    'ussr:R04_T-34', 'ussr:R07_T-34-85', 'ussr:R05_KV', 'ussr:R01_IS',
    'germany:G04_PzVI_Tiger_I', 'germany:G03_PzV_Panther', 'germany:G10_PzIII_AusfJ',
    'usa:A05_M4_Sherman', 'usa:A06_M4A3E8_Sherman', 'usa:A07_T20',
]

g_cfg = {}
g_game = None


def log(*args):
    try:
        print(_TAG + ' ' + ' '.join(str(a) for a in args))
    except Exception:
        pass


def logExc(where):
    log('EXCEPTION in', where)
    for line in traceback.format_exc().splitlines():
        log('   ', line)


def V3(x, y, z):
    return Math.Vector3(x, y, z)


def clamp(a, lo, hi):
    return lo if a < lo else (hi if a > hi else a)


def angleDiff(a, b):
    d = (a - b) % (2 * math.pi)
    if d > math.pi:
        d -= 2 * math.pi
    return d


def approachAngle(cur, target, maxStep):
    d = angleDiff(target, cur)
    if abs(d) <= maxStep:
        return target
    return cur + (maxStep if d > 0 else -maxStep)


def dirFromYawPitch(yaw, pitch):
    # pitch > 0 means looking down (BigWorld convention)
    cp = math.cos(pitch)
    return V3(math.sin(yaw) * cp, -math.sin(pitch), math.cos(yaw) * cp)


def cross(a, b):
    return V3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


def uni(s):
    if isinstance(s, unicode):
        return s
    try:
        return s.decode('utf-8')
    except Exception:
        return unicode(s, errors='replace')


def setText(g, s):
    try:
        g.text = uni(s)
    except Exception:
        try:
            g.text = s
        except Exception:
            pass


def worldFromLookAt(pos, fwd, up):
    m = Math.Matrix()
    m.lookAt(pos, fwd, up)
    m.invert()
    return m


# --------------------------------------------------------------------------- world queries
def collideStatic(spaceID, start, end):
    try:
        res = BigWorld.wg_collideSegment(spaceID, start, end, 128)
        if res is not None:
            return res.closestPoint
    except Exception:
        pass
    return None


def collideStaticMat(spaceID, start, end):
    try:
        res = BigWorld.wg_collideSegment(spaceID, start, end, 128)
        if res is not None:
            name = 'ground'
            try:
                import material_kinds
                idx = material_kinds.EFFECT_MATERIAL_INDEXES_BY_IDS.get(res.matKind)
                if idx is not None:
                    name = material_kinds.EFFECT_MATERIALS[idx]
            except Exception:
                pass
            return res.closestPoint, name
    except Exception:
        pass
    return None, None


def groundHeight(spaceID, x, z, refY):
    p = collideStatic(spaceID, V3(x, refY + 2.5, z), V3(x, refY - 60.0, z))
    if p is None:
        p = collideStatic(spaceID, V3(x, 1000.0, z), V3(x, -500.0, z))
    return None if p is None else p.y


# --------------------------------------------------------------------------- effects
_staticEffects = None


def staticEffects():
    global _staticEffects
    if _staticEffects is None:
        from helpers import bound_effects
        _staticEffects = bound_effects.StaticSceneBoundEffects()
    return _staticEffects


_effectStats = {'ok': 0, 'fail': 0}
_effectModels = []


def _effectModel(spaceID, position, direction):
    try:
        import helpers
        model = helpers.newFakeModel()
    except Exception:
        model = BigWorld.Model('')
    BigWorld.addModel(model, spaceID)
    model.position = position
    try:
        if direction is not None:
            model.rotate(direction.yaw, (0.0, 1.0, 0.0))
    except Exception:
        pass
    return model


def playEffectAt(effectsDescr, keys, position, direction, spaceID=None):
    """Plays a shot effect timeline at a world position on a standalone world model."""
    if effectsDescr is None:
        return False
    if spaceID is None:
        spaceID = g_game.spaceID if g_game is not None else BigWorld.camera().spaceID
    for key in keys:
        item = effectsDescr.get(key) if hasattr(effectsDescr, 'get') else None
        if not item:
            continue
        try:
            keyPoints, effects = item[0], item[1]
            from helpers.EffectsList import EffectsListPlayer
            model = _effectModel(spaceID, position, direction)
            holder = {}

            def onStop(*args):
                try:
                    BigWorld.delModel(holder['model'])
                except Exception:
                    pass
                try:
                    _effectModels.remove(holder['model'])
                except Exception:
                    pass
            holder['model'] = model
            _effectModels.append(model)
            player = EffectsListPlayer(effects, keyPoints, dir=direction, start=position - direction,
                                       end=position + direction, attackerID=0, entity_id=0)
            player.play(model, None, onStop)
            holder['player'] = player
            _effectStats['ok'] += 1
            if _effectStats['ok'] in (1, 10, 100):
                log('effects played:', _effectStats['ok'], 'last key', key)
            return True
        except Exception:
            _effectStats['fail'] += 1
            if _effectStats['fail'] <= 5:
                logExc('playEffectAt ' + key)
            # fallback: built-in static scene effects
            try:
                keyPoints, effects = item[0], item[1]
                staticEffects().addNew(position, effects, keyPoints, None, dir=direction,
                                       start=position - direction, end=position + direction, attackerID=0)
                return True
            except Exception:
                if _effectStats['fail'] <= 5:
                    logExc('playEffectAt fallback ' + key)
            return False
    return False


# --------------------------------------------------------------------------- floating 3D text
class FloatText(object):

    def __init__(self, spaceID, position, text, colour, life=1.6, size=1.2):
        self.pos = Math.Vector3(position)
        self.life = life
        self.total = life
        self.colour = colour
        self.alive = True
        try:
            att = GUI.Attachment()
            comp = GUI.Text(uni(text))
            att.component = comp
            att.faceCamera = True
            comp.visible = True
            comp.explicitSize = True
            comp.filterType = GUI.Simple.eFilterType.LINEAR
            comp.verticalAnchor = GUI.Simple.eVAnchor.BOTTOM
            comp.size = (0, size)
            comp.colour = colour
            self.mat = Math.Matrix()
            self.mat.setTranslate(self.pos)
            self.servo = BigWorld.Servo(self.mat)
            self.model = BigWorld.Model('')
            self.model.addMotor(self.servo)
            BigWorld.addModel(self.model, spaceID)
            self.model.root.attach(att)
            self.comp = comp
        except Exception:
            logExc('FloatText')
            self.alive = False
            self.model = None

    def tick(self, dt):
        if not self.alive:
            return
        self.life -= dt
        if self.life <= 0:
            self.destroy()
            return
        self.pos.y += dt * 1.5
        self.mat.setTranslate(self.pos)
        self.servo.signal = self.mat
        a = int(255 * min(1.0, self.life / (self.total * 0.5)))
        try:
            self.comp.colour = (self.colour[0], self.colour[1], self.colour[2], a)
        except Exception:
            pass

    def destroy(self):
        self.alive = False
        if self.model is not None:
            try:
                BigWorld.delModel(self.model)
            except Exception:
                pass
            self.model = None


# --------------------------------------------------------------------------- tracks (experimental)
class TrackRig(object):
    """Animated tracks/wheels, the same way the kill-cam drives client-only vehicles:
    CGF game object + WGVehicleFilter + model_assembler track components + PyTrackScroll.setExternal."""

    def __init__(self, tank, refs):
        self.tank = tank
        self.ok = False
        self.scrollCtl = None
        self.filter = None
        self.steps = []
        d = tank.vDesc
        sid = tank.game.spaceID
        self.typeDescriptor = d
        self.compoundModel = tank.model
        self.id = tank.entityID
        self.fashion = tank.fashions[0] if getattr(tank, 'fashions', None) else None
        self.splineTracks = None
        import CGF
        from vehicle_systems import model_assembler as ma
        queue = CGF.CommandQueue(sid)
        ent = BigWorld.entities.get(tank.entityID)

        def step(name, fn):
            try:
                r = fn()
                self.steps.append(name + ':ok')
                return r
            except Exception:
                self.steps.append(name + ':FAIL')
                logExc('TrackRig.' + name + ' ' + tank.typeName)
                return None

        def mkGo():
            go = queue.createGameObject('SandboxTank_%d' % tank.entityID)
            parent = getattr(ent, 'entityGameObject', None)
            if parent is not None:
                queue.createComponent(go, CGF.HierarchyComponent, parent)
            else:
                queue.createComponent(go, CGF.HierarchyComponent)
            queue.createComponent(go, CGF.TransformComponent, Math.Matrix())
            return go
        self.gameObject = step('gameObject', mkGo)
        if self.gameObject is None:
            return
        self.filter = step('filter', lambda: ma.createVehicleFilter(d))
        if self.filter is not None and ent is not None:
            step('entityFilter', lambda: setattr(ent, 'filter', self.filter))
        self.splineTracks = step('splineTracks', lambda: ma.setupSplineTracks(self.fashion, d, tank.model, refs, ''))
        try:
            from vehicle_systems.tankStructure import ColliderTypes
            collider = ColliderTypes.VEHICLE_COLLIDER
        except Exception:
            collider = 0
        step('wheels', lambda: ma.createWheelsAnimator(self, collider, d, (lambda: 0), self.splineTracks, queue))
        step('trackNodes', lambda: ma.createTrackNodesAnimator(self, d, queue))
        step('tracks', lambda: ma.assembleTracks(refs, d, self, self.splineTracks, True, queue))

        def mkScroll():
            sc = BigWorld.PyTrackScroll()
            sc.activate()
            if self.filter is not None:
                sc.setData(self.filter)
            return sc
        self.scrollCtl = step('trackScroll', mkScroll)
        step('activate', lambda: self.gameObject.activate())
        self.ok = self.scrollCtl is not None
        log('TrackRig', tank.typeName, ' '.join(self.steps))

    def update(self, pos, yaw, pitch, roll, speed, yawRate):
        if self.filter is not None:
            try:
                self.filter.reset()
                self.filter.input(BigWorld.time(), self.tank.game.spaceID, 0, pos, (0, 0, 0), (roll, pitch, yaw))
            except Exception:
                if 'filterInput' not in self.steps:
                    self.steps.append('filterInput')
                    logExc('TrackRig.filter.input')
        if self.scrollCtl is not None:
            half = self.tank.halfWid
            left = speed + yawRate * half
            right = speed - yawRate * half
            try:
                self.scrollCtl.setExternal(left, right)
            except Exception:
                if 'setExternal' not in self.steps:
                    self.steps.append('setExternal')
                    logExc('TrackRig.setExternal')

    def destroy(self):
        try:
            if self.scrollCtl is not None:
                self.scrollCtl.deactivate()
        except Exception:
            pass
        try:
            import CGF
            CGF.CommandQueue(self.tank.game.spaceID).removeGameObject(self.gameObject)
        except Exception:
            pass
        self.scrollCtl = None


# --------------------------------------------------------------------------- shots
SHELL_LABELS = {
    'armor_piercing': 'ББ', 'armor_piercing_cr': 'БП', 'armor_piercing_he': 'ББ',
    'high_explosive': 'ОФ', 'hollow_charge': 'КС', 'smoke': 'ДЫМ',
}


class ShotInfo(object):

    def __init__(self, shot):
        from items import vehicles as _v
        sh = shot.shell
        self.speed = shot.speed
        self.gravity = shot.gravity
        self.maxShotDist = shot.maxDistance
        self.damage = sh.armorDamage[0]
        self.piercing = shot.piercingPower[0]
        self.caliber = sh.caliber
        try:
            self.kind = str(sh.kind).lower()
        except Exception:
            self.kind = 'armor_piercing'
        self.label = SHELL_LABELS.get(self.kind, self.kind[:3].upper())
        try:
            self.effects = _v.g_cache.shotEffects[sh.effectsIndex]
        except Exception:
            self.effects = None


# --------------------------------------------------------------------------- tank
PART_NAMES = ('chassis', 'hull', 'turret', 'gun')


class Tank(object):

    def __init__(self, game, typeName, team, pos, yaw, isPlayer=False):
        from items import vehicles
        self.game = game
        self.team = team
        self.isPlayer = isPlayer
        nationID, innationID = vehicles.g_list.getIDsByName(typeName)
        self.vDesc = vehicles.VehicleDescr(typeID=(nationID, innationID))
        self.typeName = typeName
        self.userName = uni(getattr(self.vDesc.type, 'shortUserString', None) or getattr(self.vDesc.type, 'userString', None) or typeName).encode('utf-8')
        self.maxHp = float(self.vDesc.maxHealth)
        self.hp = self.maxHp
        self.alive = True
        self.loaded = False
        self.pos = Math.Vector3(pos)
        self.yaw = yaw
        self.speed = 0.0
        self.throttle = 0.0
        self.steer = 0.0
        self.turretYaw = 0.0
        self.gunPitch = 0.0
        self.reloadLeft = 1.5
        self.dispersion = 1.0
        self.matrix = Math.Matrix()
        self.matrix.setRotateYPR((yaw, 0, 0))
        self.matrix.translation = self.pos
        self.turretMatrix = Math.Matrix()
        self.gunMatrix = Math.Matrix()
        self.entityID = None
        self.trackRig = None
        self.prevYaw = yaw
        self.model = None
        self.deadModel = None
        self.marker = None
        self.kills = 0
        d = self.vDesc
        self.maxFwd = d.type.speedLimits[0]
        self.maxBack = d.type.speedLimits[1]
        self.rotSpeed = d.chassis.rotationSpeed
        self.turretSpeed = d.turret.rotationSpeed
        self.gunSpeed = d.gun.rotationSpeed
        self.pitchMin, self.pitchMax = d.gun.pitchLimits['absolute']
        self.reloadTime = d.gun.reloadTime
        self.aimingTime = d.gun.aimingTime
        self.dispAngle = d.gun.shotDispersionAngle
        self.shots = []
        try:
            for shot in d.gun.shots:
                try:
                    self.shots.append(ShotInfo(shot))
                except Exception:
                    logExc('ShotInfo')
        except Exception:
            logExc('gun.shots')
        if not self.shots:
            self.shots = [ShotInfo(d.shot)]
        self.shotIdx = 0
        self.ammo = self.__initialAmmo() if isPlayer else None
        self.repairKits = int(g_cfg.get('repairs', 3)) if isPlayer else 0
        self.repairCooldown = 0.0
        self.turretPos = d.chassis.hullPosition + d.hull.turretPositions[0]
        self.gunOffset = d.turret.gunPosition
        self.halfLen = 3.0
        self.halfWid = 1.6
        self.height = 2.2
        self.__loadHitTesters()
        self.__createEntity()
        self.__loadModels()

    # ---------------- ammo / repair
    @property
    def shotInfo(self):
        return self.shots[self.shotIdx]

    @property
    def shotEffects(self):
        return self.shotInfo.effects

    def __initialAmmo(self):
        try:
            total = int(self.vDesc.gun.maxAmmo)
        except Exception:
            total = 50
        total = max(total, 10)
        n = len(self.shots)
        shares = {1: [1.0], 2: [0.7, 0.3], 3: [0.6, 0.25, 0.15]}.get(n, [1.0 / n] * n)
        counts = [int(round(total * k)) for k in shares]
        counts[0] += total - sum(counts)
        return counts

    def selectShot(self, idx):
        if idx >= len(self.shots) or idx == self.shotIdx:
            return False
        self.shotIdx = idx
        self.reloadLeft = self.reloadTime
        return True

    def useRepair(self):
        if self.repairKits <= 0 or self.repairCooldown > 0 or not self.alive:
            return False
        if self.hp >= self.maxHp:
            return False
        self.hp = min(self.maxHp, self.hp + self.maxHp * float(g_cfg.get('repairhp', 0.4)))
        self.repairKits -= 1
        self.repairCooldown = 15.0
        return True

    def resupply(self):
        if self.isPlayer:
            self.ammo = self.__initialAmmo()

    # ---------------- setup
    def __loadHitTesters(self):
        """Client has no BSP hit testers (server only), so tanks are approximated by two boxes."""
        d = self.vDesc
        try:
            cp = d.chassis.topRightCarryingPoint
            self.halfWid = max(1.2, cp[0] + 0.35)
            self.halfLen = max(2.0, cp[1] + 0.6)
        except Exception:
            pass
        try:
            hullTop = d.chassis.hullPosition.y + d.hull.turretPositions[0].y
        except Exception:
            hullTop = 1.6
        self.hullTop = max(1.0, hullTop)
        self.height = self.hullTop + 1.0
        tp = self.turretPos
        tw = self.halfWid * 0.62
        self.boxes = (
            ('hull', V3(-self.halfWid, 0.25, -self.halfLen), V3(self.halfWid, self.hullTop, self.halfLen)),
            ('turret', V3(tp.x - tw, self.hullTop, tp.z - tw * 1.1), V3(tp.x + tw, self.hullTop + 1.0, tp.z + tw * 1.1)),
        )
        try:
            self.armor = {'hull': tuple(d.hull.primaryArmor), 'turret': tuple(d.turret.primaryArmor)}
        except Exception:
            self.armor = {'hull': (80.0, 60.0, 40.0), 'turret': (80.0, 60.0, 40.0)}

    def __createEntity(self):
        sid = self.game.spaceID
        self.entityID = BigWorld.createEntity('EmptyEntity', sid, 0, self.pos, (0, 0, self.yaw), {})

    def __loadModels(self):
        from vehicle_systems import model_assembler
        from vehicle_systems.tankStructure import ModelsSetParams
        sid = self.game.spaceID
        a = model_assembler.prepareCompoundAssembler(self.vDesc, ModelsSetParams('', 'undamaged', []), sid)
        a.name = 'alive'
        b = model_assembler.prepareCompoundAssembler(self.vDesc, ModelsSetParams('', 'destroyed', []), sid)
        b.name = 'dead'
        resources = [a, b]
        try:
            splineDesc = self.vDesc.chassis.splineDesc
            if splineDesc is not None:
                for trackDesc in splineDesc.trackPairs.values():
                    resources += trackDesc.prerequisites('')
        except Exception:
            pass
        if g_cfg.get('tracks', '1') != '0':
            try:
                for name, builders in self.vDesc.chassis.physicalTracks.items():
                    for index, builder in enumerate(builders):
                        resources.append(builder.createLoader(sid, '{0}{1}PhysicalTrack'.format(name, index), ''))
            except Exception:
                logExc('physicalTracks loaders')
        BigWorld.loadResourceListBG(tuple(resources), self.__onLoaded)

    def __onLoaded(self, refs):
        try:
            failed = refs.failedIDs
            if 'alive' in failed:
                log('model load FAILED for', self.typeName, failed)
                return
            if self.game is None or self.game.destroyed:
                return
            self.model = refs['alive']
            if 'dead' not in failed:
                self.deadModel = refs['dead']
            self.__setupFashions(self.model)
            ent = BigWorld.entities.get(self.entityID)
            if ent is None:
                log('entity vanished', self.typeName)
                return
            ent.model = self.model
            self.model.matrix = self.matrix
            tn = self.model.node('HP_turretJoint')
            if tn is not None:
                tn.local = self.turretMatrix
            self.__updatePartMatrices()
            self.loaded = True
            self.trackRig = None
            if g_cfg.get('tracks', '1') != '0':
                try:
                    self.trackRig = TrackRig(self, refs)
                except Exception:
                    logExc('TrackRig')
            if not self.isPlayer:
                self.__createMarker()
            log('loaded', self.typeName, 'team', self.team)
        except Exception:
            logExc('Tank.__onLoaded')

    def __setupFashions(self, model):
        try:
            fashions = (BigWorld.WGVehicleFashion(), BigWorld.WGBaseFashion(), BigWorld.WGBaseFashion(), BigWorld.WGBaseFashion())
            try:
                from vehicle_systems import model_assembler
                model_assembler.setupTracksFashion(self.vDesc, fashions[0])
            except Exception:
                pass
            model.setupFashions(fashions)
            self.fashions = fashions
        except Exception:
            logExc('setupFashions')

    def __createMarker(self):
        try:
            att = GUI.Attachment()
            comp = GUI.Text(uni(self.__markerText()))
            att.component = comp
            att.faceCamera = True
            comp.visible = True
            comp.multiline = True
            comp.explicitSize = True
            comp.filterType = GUI.Simple.eFilterType.LINEAR
            comp.verticalAnchor = GUI.Simple.eVAnchor.BOTTOM
            comp.size = (0, 0.9)
            comp.colour = (255, 80, 60, 255) if self.team != self.game.playerTeam else (90, 255, 90, 255)
            mat = Math.Matrix()
            servo = BigWorld.Servo(mat)
            m = BigWorld.Model('')
            m.addMotor(servo)
            BigWorld.addModel(m, self.game.spaceID)
            m.root.attach(att)
            self.marker = (m, servo, comp, mat)
        except Exception:
            logExc('createMarker')
            self.marker = None

    def __markerText(self):
        return u'%s\n%d / %d' % (uni(self.userName), max(0, int(self.hp)), int(self.maxHp))

    # ---------------- per-frame
    def __updatePartMatrices(self):
        m = Math.Matrix()
        m.setRotateY(self.turretYaw)
        tr = Math.Matrix()
        try:
            tr.setRotateX(self.vDesc.hull.turretPitches[0])
        except Exception:
            tr.setIdentity()
        tr.translation = self.vDesc.hull.turretPositions[0]
        m.postMultiply(tr)
        self.turretMatrix.set(m)
        if self.model is not None:
            try:
                gn = self.model.node('Gun') or self.model.node('gun')
                g = Math.Matrix()
                g.setRotateYPR((0, self.gunPitch, 0))
                gn.localMatrix = g
            except Exception:
                pass

    def partWorldMatrix(self, name):
        try:
            node = self.model.node(name)
            if node is not None:
                return Math.Matrix(node)
        except Exception:
            pass
        return Math.Matrix(self.matrix)

    def muzzle(self):
        try:
            node = self.model.node('HP_gunFire')
            if node is not None:
                m = Math.Matrix(node)
                return m.translation, m.applyToAxis(2)
        except Exception:
            pass
        m = self.partWorldMatrix('gun')
        d = m.applyToAxis(2)
        d.normalise()
        return m.translation + d * 3.0, d

    def center(self):
        return self.pos + V3(0, self.height * 0.6, 0)

    def turretWorldPos(self):
        return self.matrix.applyPoint(self.turretPos)

    def drive(self, dt):
        if not self.alive:
            self.speed *= max(0.0, 1.0 - dt * 3)
            self.throttle = self.steer = 0.0
        target = self.throttle * (self.maxFwd if self.throttle >= 0 else self.maxBack)
        accel = (self.maxFwd / 3.5) if abs(target) > abs(self.speed) else (self.maxFwd / 1.2)
        if self.speed < target:
            self.speed = min(target, self.speed + accel * dt)
        else:
            self.speed = max(target, self.speed - accel * dt)
        speedFactor = 1.0 - 0.35 * abs(self.speed) / max(self.maxFwd, 1.0)
        self.yaw += self.steer * self.rotSpeed * speedFactor * dt
        fwd = V3(math.sin(self.yaw), 0, math.cos(self.yaw))
        newPos = self.pos + fwd * (self.speed * dt)
        sid = self.game.spaceID
        if abs(self.speed) > 0.05:
            sign = 1.0 if self.speed > 0 else -1.0
            probeFrom = self.pos + V3(0, 1.3, 0)
            probeTo = newPos + fwd * (sign * (self.halfLen + 0.3)) + V3(0, 1.3, 0)
            if collideStatic(sid, probeFrom, probeTo) is not None:
                self.speed = 0.0
                newPos = self.pos
        bb = self.game.bounds
        newPos.x = clamp(newPos.x, bb[0] + 5, bb[2] - 5)
        newPos.z = clamp(newPos.z, bb[1] + 5, bb[3] - 5)
        h = groundHeight(sid, newPos.x, newPos.z, self.pos.y)
        if h is not None:
            newPos.y = h
        self.pos = newPos
        self.__orient()

    def __orient(self):
        sid = self.game.spaceID
        fwd = V3(math.sin(self.yaw), 0, math.cos(self.yaw))
        right = V3(fwd.z, 0, -fwd.x)
        p = self.pos
        hf = groundHeight(sid, p.x + fwd.x * self.halfLen, p.z + fwd.z * self.halfLen, p.y)
        hb = groundHeight(sid, p.x - fwd.x * self.halfLen, p.z - fwd.z * self.halfLen, p.y)
        hr = groundHeight(sid, p.x + right.x * self.halfWid, p.z + right.z * self.halfWid, p.y)
        hl = groundHeight(sid, p.x - right.x * self.halfWid, p.z - right.z * self.halfWid, p.y)
        hf = p.y if hf is None else hf
        hb = p.y if hb is None else hb
        hr = p.y if hr is None else hr
        hl = p.y if hl is None else hl
        f = V3(fwd.x * 2 * self.halfLen, hf - hb, fwd.z * 2 * self.halfLen)
        r = V3(right.x * 2 * self.halfWid, hr - hl, right.z * 2 * self.halfWid)
        f.normalise()
        r.normalise()
        up = cross(f, r)
        if up.y < 0:
            up = up * -1.0
        up.normalise()
        self.pos.y = max(self.pos.y, (hf + hb) * 0.5)
        self.matrix.set(worldFromLookAt(self.pos, f, up))

    def aimAt(self, point, dt):
        """Rotate turret/gun towards world point. Returns angular error (rad)."""
        inv = Math.Matrix(self.matrix)
        inv.invert()
        local = inv.applyPoint(point) - self.turretPos
        yaw = math.atan2(local.x, local.z)
        lim = self.vDesc.gun.turretYawLimits
        if lim is not None:
            yaw = clamp(yaw, lim[0], lim[1])
        oldYaw = self.turretYaw
        self.turretYaw = approachAngle(self.turretYaw, yaw, self.turretSpeed * dt)
        # gun pitch with ballistic arc
        rel = local - V3(0, self.gunOffset.y, 0)
        dist = math.sqrt(rel.x * rel.x + rel.z * rel.z)
        h = rel.y
        v = self.shotInfo.speed
        g = self.shotInfo.gravity
        pitch = -math.atan2(h, max(dist, 0.1))
        if g > 0 and dist > 1:
            disc = v ** 4 - g * (g * dist * dist + 2 * h * v * v)
            if disc >= 0:
                pitch = -math.atan((v * v - math.sqrt(disc)) / (g * dist))
        pitch = clamp(pitch, self.pitchMin, self.pitchMax)
        oldPitch = self.gunPitch
        self.gunPitch = approachAngle(self.gunPitch, pitch, self.gunSpeed * dt)
        moved = abs(angleDiff(self.turretYaw, oldYaw)) + abs(self.gunPitch - oldPitch)
        self.__updatePartMatrices()
        return abs(angleDiff(self.turretYaw, yaw)) + abs(self.gunPitch - pitch), moved

    def updateDispersion(self, dt, rotated):
        mv = abs(self.speed) / max(self.maxFwd, 1.0)
        target = 1.0 + 2.5 * mv + 25.0 * rotated / max(dt, 0.001) * 0.05
        if target > self.dispersion:
            self.dispersion = min(4.0, target)
        else:
            # converge: ~ 2.5x per aimingTime
            k = math.exp(-dt / max(self.aimingTime, 0.2) * 0.9)
            self.dispersion = max(1.0, target + (self.dispersion - target) * k)

    def tick(self, dt):
        if self.reloadLeft > 0:
            self.reloadLeft -= dt
        if self.repairCooldown > 0:
            self.repairCooldown -= dt
        self.drive(dt)
        if self.trackRig is not None and self.alive and dt > 0:
            yawRate = angleDiff(self.yaw, self.prevYaw) / dt
            m = self.matrix
            self.trackRig.update(self.pos, m.yaw, m.pitch, m.roll, self.speed, yawRate)
        self.prevYaw = self.yaw
        if self.marker is not None:
            m, servo, comp, mat = self.marker
            mat.setTranslate(self.pos + V3(0, self.height + 2.5, 0))
            servo.signal = mat

    def canShoot(self):
        if self.ammo is not None and self.ammo[self.shotIdx] <= 0:
            return False
        return self.alive and self.loaded and self.reloadLeft <= 0

    def shoot(self):
        if not self.canShoot():
            return
        self.reloadLeft = self.reloadTime * (1.0 if self.isPlayer else random.uniform(1.0, 1.25))
        start, d = self.muzzle()
        d.normalise()
        ang = self.dispAngle * self.dispersion
        r = ang * math.sqrt(random.random()) * 0.6
        phi = random.random() * 2 * math.pi
        up = V3(0, 1, 0)
        side = cross(d, up)
        side.normalise()
        up2 = cross(side, d)
        d = d + side * (math.cos(phi) * r) + up2 * (math.sin(phi) * r)
        d.normalise()
        self.dispersion = min(4.0, self.dispersion + 1.5)
        if self.ammo is not None:
            self.ammo[self.shotIdx] -= 1
        info = self.shotInfo
        self.game.spawnShell(self, info, start, d * info.speed)
        try:
            eff = self.vDesc.gun.effects
            if eff is not None and not hasattr(eff, 'effectsList') and isinstance(eff, (list, tuple)) and eff:
                eff = eff[0]
            if eff is not None and self.model is not None:
                from helpers.EffectsList import EffectsListPlayer
                stages, effects = eff[0], eff[1]
                pl = EffectsListPlayer(effects, stages)
                pl.play(self.model, None, None)
        except Exception:
            logExc('gun effect')

    def applyHit(self, damage):
        if not self.alive:
            return False
        self.hp -= damage
        if self.marker is not None:
            try:
                setText(self.marker[2], self.__markerText())
            except Exception:
                pass
        if self.hp <= 0:
            self.hp = 0
            self.die()
            return True
        return False

    def die(self):
        self.alive = False
        if self.trackRig is not None:
            self.trackRig.update(self.pos, self.yaw, 0, 0, 0, 0)
        try:
            ent = BigWorld.entities.get(self.entityID)
            if ent is not None and self.deadModel is not None:
                self.__setupFashions(self.deadModel)
                ent.model = self.deadModel
                self.deadModel.matrix = self.matrix
                self.model = self.deadModel
        except Exception:
            logExc('die swap model')
        if self.marker is not None:
            try:
                self.marker[2].colour = (150, 150, 150, 200)
                setText(self.marker[2], self.userName)
            except Exception:
                pass
        playEffectAt(self.shotEffects, ('armorHit', 'armorCriticalHit'), self.center(), V3(0, -1, 0))

    def destroy(self):
        if self.trackRig is not None:
            self.trackRig.destroy()
            self.trackRig = None
        try:
            if self.marker is not None:
                BigWorld.delModel(self.marker[0], self.game.spaceID) if hasattr(BigWorld, 'delModel') else None
        except Exception:
            pass
        self.marker = None
        try:
            ent = BigWorld.entities.get(self.entityID)
            if ent is not None:
                ent.model = None
            BigWorld.destroyEntity(self.entityID)
        except Exception:
            logExc('destroy entity')
        self.model = self.deadModel = None

    # ---------------- hit testing
    def hitTest(self, start, end):
        """Segment vs. oriented boxes. Returns (dist, partName, hitAngleCos, face) or None."""
        if not self.loaded:
            return None
        inv = Math.Matrix(self.matrix)
        inv.invert()
        a = inv.applyPoint(start)
        b = inv.applyPoint(end)
        dv = b - a
        L = dv.length
        if L < 1e-4:
            return None
        best = None
        for name, lo, hi in self.boxes:
            tmin, tmax, face = 0.0, 1.0, None
            ok = True
            for axis, nm in ((0, ('left', 'right')), (1, ('bottom', 'top')), (2, ('rear', 'front'))):
                o, dd, l, h = a[axis], dv[axis], lo[axis], hi[axis]
                if abs(dd) < 1e-9:
                    if o < l or o > h:
                        ok = False
                        break
                    continue
                t1, t2 = (l - o) / dd, (h - o) / dd
                f1 = nm[0]
                if t1 > t2:
                    t1, t2 = t2, t1
                    f1 = nm[1]
                if t1 > tmin:
                    tmin, face = t1, (f1, axis)
                tmax = min(tmax, t2)
                if tmin > tmax:
                    ok = False
                    break
            if not ok or face is None:
                continue
            cosA = abs(dv[face[1]]) / L
            dist = tmin * L
            if best is None or dist < best[0]:
                best = (dist, name, cosA, face[0])
        return best

    def armorAt(self, part, face):
        front, side, rear = self.armor.get(part, (80.0, 60.0, 40.0))
        if face == 'front':
            return float(front)
        if face == 'rear':
            return float(rear)
        if face in ('left', 'right'):
            return float(side)
        if face == 'top':
            return float(rear) * 0.6
        return float(rear) * 0.5


# --------------------------------------------------------------------------- shells
class Shell(object):

    def __init__(self, game, owner, info, pos, vel):
        self.game = game
        self.owner = owner
        self.info = info
        self.pos = Math.Vector3(pos)
        self.vel = Math.Vector3(vel)
        self.travelled = 0.0
        self.dead = False
        self.model = None
        self.mat = Math.Matrix()
        self.mat.setTranslate(self.pos)
        try:
            fx = info.effects
            if fx is not None and 'projectile' in fx:
                modelName, ownModelName, projEffects = fx['projectile']
                name = ownModelName if owner.isPlayer else modelName
                self.model = BigWorld.Model(name)
                self.servo = BigWorld.Servo(self.mat)
                self.model.addMotor(self.servo)
                BigWorld.addModel(self.model, game.spaceID)
                self.model.visible = True
                self.effectsData = {}
                try:
                    projEffects.attachTo(self.model, self.effectsData, 'flying', isPlayerVehicle=owner.isPlayer,
                                         isArtillery=False, attackerID=0, collisionTime=0)
                except Exception:
                    pass
        except Exception:
            logExc('Shell model')
            self.model = None

    def tick(self, dt):
        g = self.info.gravity
        newVel = self.vel - V3(0, g * dt, 0)
        newPos = self.pos + (self.vel + newVel) * (0.5 * dt)
        hit = self.game.traceShot(self, self.pos, newPos)
        if hit:
            self.finish()
            return
        self.travelled += (newPos - self.pos).length
        self.pos = newPos
        self.vel = newVel
        if self.model is not None:
            fwd = Math.Vector3(self.vel)
            fwd.normalise()
            try:
                self.mat.set(worldFromLookAt(self.pos, fwd, V3(0, 1, 0)))
            except Exception:
                self.mat.setTranslate(self.pos)
            self.servo.signal = self.mat
        if self.travelled > self.info.maxShotDist or self.pos.y < -200:
            self.finish()

    def finish(self):
        self.dead = True
        if self.model is not None:
            try:
                BigWorld.delModel(self.model)
            except Exception:
                pass
            self.model = None


# --------------------------------------------------------------------------- bot AI
class BotBrain(object):

    def __init__(self, tank, difficulty):
        self.t = tank
        self.difficulty = difficulty
        self.target = None
        self.think = random.uniform(0, 0.5)
        self.los = False
        self.stuck = 0.0
        self.unstickTimer = 0.0
        self.unstickSteer = 1.0
        self.lastPos = Math.Vector3(tank.pos)
        self.lastPosTime = 0.0
        self.strafe = random.choice((-1, 1))
        self.strafeTimer = random.uniform(3, 7)
        self.preferredRange = random.uniform(110, 220)
        self.aimErr = V3(0, 0, 0)

    def tick(self, dt, game):
        t = self.t
        if not t.alive or not t.loaded:
            t.throttle = t.steer = 0
            return
        self.think -= dt
        if self.think <= 0:
            self.think = 0.5
            self.__decide(game)
        tgt = self.target
        if tgt is None or not tgt.alive:
            t.throttle = 0.3
            t.steer = 0.0
            return
        toT = tgt.pos - t.pos
        dist = toT.length
        wantYaw = math.atan2(toT.x, toT.z)
        # movement
        if self.unstickTimer > 0:
            self.unstickTimer -= dt
            t.throttle = -0.7 if self.unstickTimer > 1.0 else 0.8
            t.steer = self.unstickSteer
        else:
            if not self.los or dist > self.preferredRange + 40:
                moveYaw = wantYaw
                t.throttle = 1.0
            elif dist < self.preferredRange - 50:
                moveYaw = wantYaw + math.pi * 0.5 * self.strafe
                t.throttle = 0.6
            else:
                moveYaw = wantYaw + math.pi * 0.5 * self.strafe
                t.throttle = 0.35 if random.random() < 0.97 else 0.0
            d = angleDiff(moveYaw, t.yaw)
            t.steer = clamp(d * 2.0, -1.0, 1.0)
            if abs(d) > 1.2:
                t.throttle *= 0.3
        self.strafeTimer -= dt
        if self.strafeTimer <= 0:
            self.strafeTimer = random.uniform(4, 9)
            self.strafe = -self.strafe
        # aim + shoot
        aimPoint = tgt.center() + self.aimErr
        err, rotated = t.aimAt(aimPoint, dt)
        t.updateDispersion(dt, rotated)
        if self.los and dist < 500 and err < 0.02 and t.canShoot():
            if t.dispersion < 1.6 or random.random() < 0.01 * self.difficulty:
                t.shoot()
                self.__newAimError(dist)

    def __newAimError(self, dist):
        k = (dist / 100.0) * 1.2 / max(self.difficulty, 0.2)
        self.aimErr = V3(random.gauss(0, k), random.gauss(0, k * 0.5), random.gauss(0, k))

    def __decide(self, game):
        t = self.t
        best, bestD = None, 1e9
        for o in game.tanks:
            if o.team == t.team or not o.alive or not o.loaded:
                continue
            dd = (o.pos - t.pos).length
            if dd < bestD:
                best, bestD = o, dd
        if best is not self.target:
            self.target = best
            self.__newAimError(bestD)
        if best is not None:
            a = t.turretWorldPos() + V3(0, 0.3, 0)
            b = best.center()
            p = collideStatic(game.spaceID, a, b)
            self.los = p is None or (p - a).length > (b - a).length - 2.0
        # stuck detection
        self.lastPosTime += 0.5
        if self.lastPosTime >= 2.0:
            moved = (t.pos - self.lastPos).length
            if abs(t.throttle) > 0.3 and moved < 1.0 and self.unstickTimer <= 0:
                self.unstickTimer = 2.5
                self.unstickSteer = random.choice((-1.0, 1.0))
            self.lastPos = Math.Vector3(t.pos)
            self.lastPosTime = 0.0


# --------------------------------------------------------------------------- game
class SandboxGame(object):

    def __init__(self, cfg):
        self.cfg = cfg
        self.destroyed = False
        self.spaceID = None
        self.tanks = []
        self.brains = []
        self.shells = []
        self.player = None
        self.playerTeam = 1
        self.camYaw = 0.0
        self.camPitch = 0.25
        self.camDist = 14.0
        self.sniper = False
        self.mouseLook = True
        self.lastTime = None
        self.callbackID = None
        self.gui = {}
        self.messages = []
        self.state = 'loading'
        self.showHelp = True
        self.helpTimer = 12.0
        self.mapName = cfg['map']
        self.arenaType = None
        self.bounds = (-500.0, -500.0, 500.0, 500.0)
        self.defaultFov = math.radians(70)
        self.aimPoint = None
        self.fireRequested = False
        self.hitTimers = {}
        self.floats = []

    # ---------------- start
    def start(self):
        log('starting sandbox v' + VERSION, self.cfg)
        self.__findArena()
        BigWorld.clearAllSpaces()
        BigWorld.worldDrawEnabled(False)
        space = BigWorld.createSpace()
        self.spaceID = space.id
        self.space = space
        mask = -1
        try:
            from SpaceVisibilityFlags import SpaceVisibilityFlagsFactory
            mask = SpaceVisibilityFlagsFactory.create('spaces/' + self.mapName).getMaskForGameplayID('ctf')
        except Exception:
            try:
                from SpaceVisibilityFlags import SpaceVisibilityFlagsFactory
                mask = SpaceVisibilityFlagsFactory.create(self.mapName).getMaskForGameplayID('ctf')
            except Exception:
                mask = -1
        BigWorld.addSpaceGeometryMapping(self.spaceID, None, 'spaces/' + self.mapName, mask, '')
        sp1, sp2 = self.__spawnPoints()
        self.spawn1, self.spawn2 = sp1, sp2
        cam = BigWorld.FreeCamera()
        cam.spaceID = self.spaceID
        BigWorld.camera(cam)
        cam.fixed = True
        self.cam = cam
        p = sp1[0]
        self.__setCamera(V3(p.x, 150, p.z), V3(0, -0.7, 0.7))
        try:
            self.defaultFov = BigWorld.projection().fov
        except Exception:
            pass
        # fake player entity (same trick as the built-in offline mode)
        eid = BigWorld.createEntity('OfflineEntity', self.spaceID, 0, V3(p.x, 0, p.z), (0, 0, 0), {})
        ent = BigWorld.entity(eid)
        self.fakeEntity = ent
        try:
            ent.playerVehicleID = 0
            ent.arena = None
        except Exception:
            pass
        BigWorld.player = lambda: ent
        self.__createGUI()
        self.__setLoadingText('Загрузка карты %s...' % self.mapName)
        try:
            GUI.mcursor().visible = False
            GUI.mcursor().clipped = True
        except Exception:
            pass
        BigWorld.callback(1.0, self.__waitSpace)

    def __findArena(self):
        try:
            import ArenaType
            cands = [a for a in ArenaType.g_cache.values() if a.geometryName == self.mapName]
            ctf = [a for a in cands if a.gameplayName == 'ctf']
            self.arenaType = (ctf or cands or [None])[0]
            if self.arenaType is None:
                log('arena type not found for', self.mapName, '- using defaults')
                return
            bb = self.arenaType.boundingBox
            self.bounds = (bb[0][0], bb[0][1], bb[1][0], bb[1][1])
            log('arena', self.arenaType.geometryName, self.arenaType.gameplayName, 'bounds', self.bounds)
        except Exception:
            logExc('findArena')

    def __spawnPoints(self):
        x0, z0, x1, z1 = self.bounds
        cx = (x0 + x1) * 0.5
        sp = [[], []]
        try:
            at = self.arenaType
            pts = at.teamSpawnPoints if at is not None else None
            if pts:
                for i in (0, 1):
                    sp[i] = [V3(p[0], 0, p[1]) for p in pts[i]]
            if (not sp[0] or not sp[1]) and at is not None and at.teamBasePositions:
                for i in (0, 1):
                    if not sp[i]:
                        sp[i] = [V3(p[0], 0, p[1]) for p in at.teamBasePositions[i].values()]
        except Exception:
            logExc('spawnPoints')
        if not sp[0]:
            sp[0] = [V3(cx, 0, z0 + (z1 - z0) * 0.15)]
        if not sp[1]:
            sp[1] = [V3(cx, 0, z1 - (z1 - z0) * 0.15)]
        return sp[0], sp[1]

    def __waitSpace(self):
        if self.destroyed:
            return
        try:
            status = BigWorld.spaceLoadStatus()
        except Exception:
            status = 1.0
        self.__setLoadingText('Загрузка карты %s... %d%%' % (self.mapName, int(status * 100)))
        if status < 0.999:
            BigWorld.callback(0.5, self.__waitSpace)
            return
        BigWorld.worldDrawEnabled(True)
        try:
            BigWorld.uniprofSceneStart()
        except Exception:
            pass
        self.__spawnAll()
        self.state = 'play'
        self.__setLoadingText('')
        self.lastTime = BigWorld.time()
        self.callbackID = BigWorld.callback(0.0, self.__tick)

    def __spawnPos(self, base, idx, count):
        ring = 12.0 + 10.0 * (idx // 5)
        a = (idx % 5) / 5.0 * 2 * math.pi + random.uniform(-0.3, 0.3)
        k = 1 if idx else 0
        x = base.x + math.cos(a) * ring * k
        z = base.z + math.sin(a) * ring * k
        p = collideStatic(self.spaceID, V3(x, 1000.0, z), V3(x, -500.0, z))
        h = p.y if p is not None else None
        return V3(x, h if h is not None else 0, z)

    def __spawnAll(self):
        for t in self.tanks:
            t.destroy()
        self.tanks, self.brains, self.shells = [], [], []
        diff = float(self.cfg.get('difficulty', 1.0))
        p1 = self.spawn1[0]
        p2 = self.spawn2[0]
        faceEnemy = math.atan2(p2.x - p1.x, p2.z - p1.z)
        try:
            self.player = Tank(self, self.cfg['tank'], 1, self.__spawnPos(p1, 0, 1), faceEnemy, isPlayer=True)
        except Exception:
            logExc('player tank ' + self.cfg['tank'])
            self.player = Tank(self, DEFAULTS['tank'], 1, self.__spawnPos(p1, 0, 1), faceEnemy, isPlayer=True)
        self.tanks.append(self.player)
        self.camYaw = faceEnemy
        nAllies = int(self.cfg.get('allies', 0))
        nBots = int(self.cfg.get('bots', 6))
        pool = list(BOT_POOL)
        for i in range(nAllies):
            self.__addBot(random.choice(pool), 1, self.__spawnPos(p1, i + 1, nAllies), faceEnemy, diff)
        n2 = len(self.spawn2)
        for i in range(nBots):
            base = self.spawn2[i % n2]
            slot = i // n2 if n2 > 1 else i
            self.__addBot(random.choice(pool), 2, self.__spawnPos(base, slot, nBots), faceEnemy + math.pi, diff)
        self.addMessage('Бой начался! Врагов: %d' % nBots, (255, 220, 120, 255))

    def __addBot(self, name, team, pos, yaw, diff):
        try:
            t = Tank(self, name, team, pos, yaw)
        except Exception:
            logExc('bot ' + name)
            return
        self.tanks.append(t)
        self.brains.append(BotBrain(t, diff))

    # ---------------- GUI
    def __text(self, key, x, y, size=None, colour=(255, 255, 255, 255), hAnchor='CENTER', vAnchor='CENTER'):
        t = GUI.Text('')
        t.multiline = True
        t.horizontalAnchor = getattr(GUI.Simple.eHAnchor, hAnchor)
        t.verticalAnchor = getattr(GUI.Simple.eVAnchor, vAnchor)
        t.position = (x, y, 0.5)
        t.colour = colour
        GUI.addRoot(t)
        self.gui[key] = t
        return t

    def __createGUI(self):
        try:
            self.__text('loading', 0, 0.1)
            self.__text('cross', 0, 0, colour=(255, 255, 255, 200)).text = u'+'
            self.__text('gunmark', 0, 0, colour=(120, 255, 120, 255)).text = 'o'
            self.__text('hud', -0.97, -0.95, hAnchor='LEFT', vAnchor='BOTTOM')
            self.__text('panel', 0, -0.95, vAnchor='BOTTOM', colour=(255, 255, 255, 255))
            self.__text('reload', 0, -0.07, colour=(255, 255, 255, 230))
            self.__text('hitinfo', 0, 0.14, colour=(255, 200, 80, 255))
            self.__text('hurt', 0, -0.22, colour=(255, 80, 80, 255))
            self.__text('enemies', 0.97, 0.90, hAnchor='RIGHT')
            self.__text('msg', 0, 0.55, colour=(255, 230, 150, 255))
            self.__text('big', 0, 0.25, colour=(255, 255, 255, 255))
            self.__text('help', -0.97, 0.60, hAnchor='LEFT', colour=(220, 220, 220, 230))
            setText(self.gui['help'], HELP_TEXT)
        except Exception:
            logExc('createGUI')

    def __setLoadingText(self, s):
        t = self.gui.get('loading')
        if t is not None:
            setText(t, s)

    def flash(self, key, text, colour, life=1.5):
        t = self.gui.get(key)
        if t is None:
            return
        setText(t, text)
        t.colour = colour
        self.hitTimers[key] = life

    def floatText(self, pos, text, colour):
        self.floats.append(FloatText(self.spaceID, pos, text, colour))

    def addMessage(self, s, colour=(255, 230, 150, 255)):
        self.messages.append([s, 4.0, colour])
        self.messages = self.messages[-5:]

    def __updateGUI(self, dt):
        p = self.player
        g = self.gui
        if not g:
            return
        try:
            if p is not None:
                rl = max(0.0, p.reloadLeft)
                bars = 20
                filled = int(round(bars * p.hp / max(p.maxHp, 1)))
                hpBar = '|' * filled + '.' * (bars - filled)
                setText(g['hud'], '%s\nПрочность: [%s] %d / %d\nСкорость: %d км/ч    Сведение: %d%%\nУничтожено: %d' % (
                    p.userName, hpBar, int(p.hp), int(p.maxHp), int(abs(p.speed) * 3.6),
                    int(100.0 / p.dispersion), p.kills))
                cells = []
                for i, sh in enumerate(p.shots):
                    cell = '%d: %s x%d' % (i + 1, sh.label, p.ammo[i])
                    cells.append(('>> %s <<' % cell) if i == p.shotIdx else cell)
                rkCell = '4: РЕМКОМПЛЕКТ x%d' % p.repairKits
                if p.repairCooldown > 0 and p.repairKits > 0:
                    rkCell += ' (%d c)' % int(p.repairCooldown + 1)
                setText(g['panel'], 'СНАРЯДЫ:   ' + '     '.join(cells) + '          ' + rkCell)
                if not p.alive:
                    setText(g['reload'], '')
                elif p.ammo[p.shotIdx] <= 0:
                    setText(g['reload'], 'НЕТ СНАРЯДОВ - нажмите 1/2/3')
                    g['reload'].colour = (255, 90, 90, 255)
                elif rl > 0:
                    setText(g['reload'], '%s  %.1f' % (p.shotInfo.label, rl))
                    g['reload'].colour = (255, 170, 90, 255)
                else:
                    setText(g['reload'], '%s  ГОТОВ' % p.shotInfo.label)
                    g['reload'].colour = (120, 255, 120, 255)
            for key in ('hitinfo', 'hurt'):
                left = self.hitTimers.get(key, 0) - dt
                self.hitTimers[key] = left
                if left <= 0 and key in g:
                    setText(g[key], '')
                g['gunmark'].colour = (120, 255, 120, 255) if p.canShoot() else (255, 120, 80, 255)
            alive = [t for t in self.tanks if t.team != self.playerTeam and t.alive]
            setText(g['enemies'], 'Врагов осталось: %d' % len(alive))
            lines = []
            for m in self.messages:
                m[1] -= dt
                if m[1] > 0:
                    lines.append(m[0])
            self.messages = [m for m in self.messages if m[1] > 0]
            setText(g['msg'], '\n'.join(lines))
            if self.showHelp:
                self.helpTimer -= dt
                if self.helpTimer <= 0:
                    self.showHelp = False
            g['help'].visible = self.showHelp
            self.__updateGunMarker()
        except Exception:
            logExc('updateGUI')

    def __updateGunMarker(self):
        p = self.player
        mk = self.gui.get('gunmark')
        if mk is None or p is None or not p.loaded:
            return
        start, d = p.muzzle()
        d.normalise()
        end = start + d * 700.0
        hitP = collideStatic(self.spaceID, start, end)
        if hitP is None:
            hitP = end
        sp = self.worldToScreen(hitP)
        if sp is None:
            mk.visible = False
        else:
            mk.visible = True
            mk.position = (sp[0], sp[1], 0.5)

    def worldToScreen(self, p):
        try:
            view = Math.Matrix(self.cam.matrix)
            v = view.applyPoint(p)
            if v.z <= 0.1:
                return None
            fov = BigWorld.projection().fov
            sw, sh = GUI.screenResolution()
            aspect = float(sw) / float(sh)
            th = math.tan(fov * 0.5)
            x = (v.x / v.z) / (th * aspect)
            y = (v.y / v.z) / th
            if abs(x) > 1.2 or abs(y) > 1.2:
                return None
            return x, y
        except Exception:
            return None

    # ---------------- camera
    def __setCamera(self, pos, fwd):
        fwd = Math.Vector3(fwd)
        fwd.normalise()
        m = Math.Matrix()
        m.lookAt(pos, fwd, V3(0, 1, 0))
        self.cam.set(m)
        self.camPos = pos
        self.camFwd = fwd

    def __updateCamera(self):
        p = self.player
        if p is None:
            return
        fwd = dirFromYawPitch(self.camYaw, self.camPitch)
        if self.sniper and p.alive:
            m = Math.Matrix(p.partWorldMatrix('turret'))
            eye = m.applyPoint(p.gunOffset + V3(0, 0.6, 0))
            self.__setCamera(eye, fwd)
        else:
            pivot = p.pos + V3(0, p.height + 1.5, 0)
            want = pivot - fwd * self.camDist
            hit = collideStatic(self.spaceID, pivot, want)
            if hit is not None:
                want = hit + fwd * 0.6
            h = groundHeight(self.spaceID, want.x, want.z, want.y)
            if h is not None and want.y < h + 0.8:
                want.y = h + 0.8
            self.__setCamera(want, fwd)
        # aim point: ray from camera
        start = self.camPos
        end = start + self.camFwd * 1000.0
        best = None
        for t in self.tanks:
            if t is p:
                continue
            r = t.hitTest(start, end)
            if r is not None and (best is None or r[0] < best):
                best = r[0]
        sp = collideStatic(self.spaceID, start + self.camFwd * 2.0, end)
        dStatic = (sp - start).length if sp is not None else 1000.0
        d = min(best if best is not None else 1e9, dStatic)
        self.aimPoint = start + self.camFwd * d

    def __setSniper(self, on):
        self.sniper = on
        try:
            BigWorld.projection().fov = self.defaultFov / (5.0 if on else 1.0)
        except Exception:
            pass
        cross = self.gui.get('cross')
        if cross is not None:
            setText(cross, '-- + --' if on else '+')

    # ---------------- shots
    def spawnShell(self, owner, info, pos, vel):
        self.shells.append(Shell(self, owner, info, pos, vel))

    def traceShot(self, shell, a, b):
        owner = shell.owner
        best = None
        for t in self.tanks:
            if t is owner:
                continue
            r = t.hitTest(a, b)
            if r is not None and (best is None or r[0] < best[0]):
                best = (r[0], t, r)
        segLen = (b - a).length
        sp, matName = collideStaticMat(self.spaceID, a, b)
        dStatic = (sp - a).length if sp is not None else None
        dirv = b - a
        dirv.normalise()
        if best is not None and (dStatic is None or best[0] <= dStatic):
            dist, target, (d, part, cosA, matKind) = best
            hitPos = a + dirv * dist
            self.__resolveTankHit(owner, shell.info, target, part, cosA, matKind, hitPos, dirv, shell.travelled + dist)
            return True
        if dStatic is not None and dStatic <= segLen + 0.01:
            playEffectAt(shell.info.effects, ((matName or 'ground') + 'Hit', 'groundHit'), sp, dirv)
            return True
        return False

    def __resolveTankHit(self, owner, info, target, part, cosA, matKind, pos, dirv, travelled):
        armor = target.armorAt(part, matKind)
        cosA = max(abs(cosA), 0.05)
        kind = info.kind
        isHE = 'high_explosive' in kind
        isAP = 'armor_piercing' in kind
        effective = armor / cosA
        ricochet = False
        penChance = float(g_cfg.get('pen', 0.95)) if owner.isPlayer else None
        if penChance is not None:
            # player: penetration mostly guaranteed, no ricochets
            if random.random() < penChance:
                armor = 0.0
            isAP = False
        if isAP and armor > 0 and cosA < math.cos(math.radians(70)) and info.caliber < 3 * armor:
            ricochet = True
        pierce = info.piercing * random.uniform(0.75, 1.25)
        if 'armor_piercing' in kind or 'hollow' in kind:
            pierce *= max(0.6, 1.0 - travelled / 2500.0)
        if not target.alive:
            playEffectAt(info.effects, ('armorResisted',), pos, dirv)
            return
        if ricochet:
            playEffectAt(info.effects, ('armorRicochet', 'armorBasicRicochet'), pos, dirv)
            if owner.isPlayer:
                self.flash('hitinfo', 'РИКОШЕТ', (160, 190, 255, 255))
                self.floatText(pos, 'Рикошет', (160, 190, 255, 255))
            elif target.isPlayer:
                self.flash('hurt', 'Рикошет от вашей брони', (160, 190, 255, 255))
            return
        if armor <= 0 or pierce >= effective:
            dmg = info.damage * random.uniform(0.75, 1.25)
            if owner.isPlayer:
                dmg *= float(g_cfg.get('dmg', 2.0))
        elif isHE:
            dmg = max(0.0, info.damage * 0.5 - effective * 1.1)
        else:
            dmg = 0.0
        if dmg <= 0:
            playEffectAt(info.effects, ('armorResisted',), pos, dirv)
            if owner.isPlayer:
                self.flash('hitinfo', 'НЕ ПРОБИЛ  (%d мм)' % int(effective), (200, 200, 200, 255))
                self.floatText(pos, 'Не пробил', (200, 200, 200, 255))
            elif target.isPlayer:
                self.flash('hurt', 'Броня выдержала', (150, 255, 150, 255))
            return
        playEffectAt(info.effects, ('armorHit', 'armorCriticalHit'), pos, dirv)
        killed = target.applyHit(dmg)
        if owner.isPlayer:
            self.flash('hitinfo', ('УНИЧТОЖЕН!  -%d' if killed else 'ПРОБИТИЕ  -%d') % int(dmg),
                       (255, 80, 60, 255) if killed else (255, 200, 80, 255))
            self.floatText(target.pos + V3(0, target.height + 1.0, 0), '-%d' % int(dmg), (255, 200, 60, 255))
        elif target.isPlayer:
            self.flash('hurt', 'ПО ВАМ  -%d  (%s)' % (int(dmg), owner.userName), (255, 80, 80, 255))
        if killed:
            owner.kills += 1
            self.addMessage('%s уничтожен' % target.userName, (255, 120, 120, 255) if target.team != self.playerTeam else (255, 60, 60, 255))
            self.__checkEnd()

    def __checkEnd(self):
        enemies = [t for t in self.tanks if t.team != self.playerTeam and t.alive]
        big = self.gui.get('big')
        if self.player is not None and not self.player.alive:
            self.state = 'over'
            if big is not None:
                setText(big, 'ВАШ ТАНК УНИЧТОЖЕН\n\nEnter - новый бой')
                big.colour = (255, 80, 80, 255)
        elif not enemies:
            self.state = 'over'
            if big is not None:
                setText(big, 'ПОБЕДА!\n\nEnter - новый бой')
                big.colour = (120, 255, 120, 255)

    def restart(self):
        big = self.gui.get('big')
        if big is not None:
            setText(big, '')
        self.__setSniper(False)
        self.__spawnAll()
        self.state = 'play'

    # ---------------- loop
    def __tick(self):
        self.callbackID = None
        if self.destroyed:
            return
        try:
            now = BigWorld.time()
            dt = clamp(now - (self.lastTime or now), 0.0, 0.1)
            self.lastTime = now
            self.__readControls()
            for b in self.brains:
                b.tick(dt, self)
            for t in self.tanks:
                t.tick(dt)
            self.__separateTanks()
            p = self.player
            if p is not None and p.alive and p.loaded:
                if self.aimPoint is not None:
                    err, rotated = p.aimAt(self.aimPoint, dt)
                    p.updateDispersion(dt, rotated)
                if (self.fireRequested or BigWorld.isKeyDown(Keys.KEY_LEFTMOUSE)) and self.state == 'play':
                    p.shoot()
            self.fireRequested = False
            for f in self.floats:
                f.tick(dt)
            self.floats = [f for f in self.floats if f.alive]
            for s in self.shells:
                s.tick(dt)
            self.shells = [s for s in self.shells if not s.dead]
            self.__updateCamera()
            self.__updateGUI(dt)
            if self.state == 'play':
                self.__checkEnd()
        except Exception:
            logExc('tick')
        self.callbackID = BigWorld.callback(0.0, self.__tick)

    def __separateTanks(self):
        ts = [t for t in self.tanks if t.loaded]
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                d = b.pos - a.pos
                d.y = 0
                dist = d.length
                minD = (a.halfLen + b.halfLen) * 0.75
                if 0.01 < dist < minD:
                    push = d * ((minD - dist) / dist * 0.5)
                    a.pos = a.pos - push
                    b.pos = b.pos + push

    def __readControls(self):
        p = self.player
        if p is None:
            return
        if not p.alive or self.state != 'play':
            p.throttle = p.steer = 0
            return
        k = BigWorld.isKeyDown
        thr = (1.0 if k(Keys.KEY_W) else 0.0) - (1.0 if k(Keys.KEY_S) else 0.0)
        st = (1.0 if k(Keys.KEY_D) else 0.0) - (1.0 if k(Keys.KEY_A) else 0.0)
        p.throttle = thr
        p.steer = st if thr >= 0 else st

    def handleKey(self, event):
        try:
            if not event.isKeyDown() or event.isRepeatedEvent():
                return True
            key = event.key
            if key == Keys.KEY_LEFTMOUSE:
                self.fireRequested = True
            elif key == Keys.KEY_ESCAPE:
                if getattr(self, '_escArmed', 0) > BigWorld.time():
                    log('quit by user')
                    BigWorld.quit()
                else:
                    self._escArmed = BigWorld.time() + 2.0
                    self.addMessage('Нажмите Esc ещё раз для выхода', (255, 255, 255, 255))
            elif key == Keys.KEY_LSHIFT or key == Keys.KEY_RIGHTMOUSE:
                self.__setSniper(not self.sniper)
            elif key == Keys.KEY_F1:
                self.showHelp = not self.showHelp
                self.helpTimer = 9999
            elif key == Keys.KEY_RETURN or key == Keys.KEY_NUMPADENTER:
                if self.state == 'over':
                    self.restart()
            elif key == Keys.KEY_F5:
                self.restart()
            elif key in (Keys.KEY_1, Keys.KEY_2, Keys.KEY_3) and self.player is not None:
                idx = {Keys.KEY_1: 0, Keys.KEY_2: 1, Keys.KEY_3: 2}[key]
                if self.player.selectShot(idx):
                    self.addMessage('Заряжаем: %s' % self.player.shotInfo.label, (220, 220, 255, 255))
            elif key == Keys.KEY_4 and self.player is not None:
                p = self.player
                if p.useRepair():
                    self.addMessage('Ремкомплект: +%d' % int(p.maxHp * float(g_cfg.get('repairhp', 0.4))), (120, 255, 120, 255))
                elif p.repairKits <= 0:
                    self.addMessage('Ремкомплекты закончились', (255, 150, 150, 255))
                elif p.repairCooldown > 0:
                    self.addMessage('Ремкомплект перезаряжается: %d c' % int(p.repairCooldown + 1), (255, 220, 150, 255))
                else:
                    self.addMessage('Танк не повреждён', (220, 220, 220, 255))
        except Exception:
            logExc('handleKey')
        return True

    def handleMouse(self, event):
        try:
            dx, dy, dz = event.dx, event.dy, event.dz
            sens = 0.0035 if not self.sniper else 0.0007
            self.camYaw += dx * sens
            self.camPitch = clamp(self.camPitch + dy * sens, -1.2, 1.3)
            if dz:
                if self.sniper:
                    if dz < 0:
                        self.__setSniper(False)
                else:
                    self.camDist = clamp(self.camDist - dz * 0.01, 5.0, 40.0)
                    if dz > 0 and self.camDist <= 5.0:
                        self.__setSniper(True)
        except Exception:
            logExc('handleMouse')
        return True


HELP_TEXT = (u'ПЕСОЧНИЦА  (F1 - скрыть/показать)\n'
             u'W/S - вперёд/назад,  A/D - повороты\n'
             u'Мышь - обзор и наведение\n'
             u'ЛКМ - выстрел,  1/2/3 - тип снаряда\n'
             u'4 - ремкомплект (+40% прочности)\n'
             u'Shift / ПКМ / колесо - снайперский режим\n'
             u'F5 - начать бой заново\n'
             u'Esc x2 - выход из игры')


# --------------------------------------------------------------------------- bootstrap
FLAG_NAME = 'sandbox_launch.txt'
_flagArgs = []


def _flagCandidates():
    import os
    dirs = []
    try:
        import ResMgr
        app = ResMgr.appDirectory()
        dirs += [app, os.path.join(app, '..')]
    except Exception:
        pass
    try:
        dirs.append(os.getcwd())
        dirs.append(os.path.join(os.getcwd(), '..'))
    except Exception:
        pass
    try:
        exe = os.path.dirname(os.path.abspath(sys.executable or ''))
        dirs += [exe, os.path.join(exe, '..')]
    except Exception:
        pass
    return [os.path.normpath(os.path.join(d, FLAG_NAME)) for d in dirs if d]


def _readFlagFile():
    """One-shot launch flag written by sandbox_bots.bat; deleted after reading."""
    import os
    result = None
    for path in set(_flagCandidates()):
        try:
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    data = f.read()
                try:
                    os.remove(path)
                except Exception:
                    log('could not delete flag file', path)
                log('flag file found:', path)
                if result is None:
                    result = data.replace('\r', ' ').replace('\n', ' ').split()
        except Exception:
            logExc('readFlagFile ' + path)
    return result


def _parseArgs():
    cfg = dict(DEFAULTS)
    for a in list(sys.argv) + _flagArgs:
        if '=' in a:
            k, v = a.split('=', 1)
            k = k.strip().lower().lstrip('-')
            if k in cfg:
                cfg[k] = v.strip()
    return cfg


def _isSandboxLaunch():
    global _flagArgs
    if any(a.lower().lstrip('-') == 'sandbox' for a in sys.argv):
        return True
    args = _readFlagFile()
    if args is not None:
        _flagArgs = args
        return True
    return False


def _onStartup():
    global g_game
    if g_cfg.get('mode') == 'freecam':
        # Built-in developer offline mode: map + free camera, no tanks.
        try:
            from helpers import OfflineMode as _om
            log('freecam mode: OfflineMode.launch', 'spaces/' + g_cfg['map'])
            _om.launch('spaces/' + g_cfg['map'])
        except Exception:
            logExc('freecam launch')
        return True
    try:
        g_game = SandboxGame(g_cfg)
        g_game.start()
        return True
    except Exception:
        logExc('startup')
        return True


def _patchInput():
    import game as _gameModule

    def handleKeyEvent(event):
        if g_game is not None:
            return g_game.handleKey(event)
        return _origKey(event)

    def handleMouseEvent(event):
        if g_game is not None:
            return g_game.handleMouse(event)
        return _origMouse(event)

    _origKey = _gameModule.handleKeyEvent
    _origMouse = _gameModule.handleMouseEvent
    _gameModule.handleKeyEvent = handleKeyEvent
    _gameModule.handleMouseEvent = handleMouseEvent


def init():
    global g_cfg
    if not _isSandboxLaunch():
        return
    try:
        g_cfg = _parseArgs()
        log('sandbox launch detected, argv =', sys.argv, 'flag =', _flagArgs, 'cfg =', g_cfg)
        from helpers import OfflineMode
        OfflineMode.onStartup = _onStartup
        if g_cfg.get('mode') != 'freecam':
            _patchInput()
        log('hooks installed')
    except Exception:
        logExc('init')


def fini():
    global g_game
    if g_game is not None:
        g_game.destroyed = True
        g_game = None
