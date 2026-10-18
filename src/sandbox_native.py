# -*- coding: utf-8 -*-
# WoT Sandbox - "native" mode (experimental).
# Runs the game's own battle client (PlayerAvatar, Vehicle, ClientArena, battle GUI) and plays the role
# of the server inside the client: every `entity.cell.X(...)` / `entity.base.X(...)` call is routed to
# NativeServer, which answers with the same client methods the real server would call.
from __future__ import absolute_import, division
import math
import random
import zlib

import BigWorld
import Math

from gui.mods import mod_sandbox as S

log = S.log
logExc = S.logExc
V3 = S.V3

VERSION = 'native-0.2'


class _Stub(object):
    """Falsy catch-all object returned for server-only config models that do not exist offline."""

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Stub()

    def __call__(self, *a, **k):
        return _Stub()

    def __nonzero__(self):
        return False

    __bool__ = __nonzero__

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __getitem__(self, k):
        return _Stub()

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __eq__(self, o):
        return isinstance(o, _Stub) or o in (None, False, 0)

    def __ne__(self, o):
        return not self.__eq__(o)

    def __hash__(self):
        return 0

    def __repr__(self):
        return '<SandboxStub>'


def _patchServerSettings():
    try:
        from helpers import server_settings
        cls = server_settings.ServerSettings
        orig = cls.getConfigModel
        missing = set()

        def getConfigModel(self, schema):
            try:
                return orig(self, schema)
            except Exception:
                key = getattr(schema, 'gpKey', schema)
                if key not in missing:
                    missing.add(key)
                    log('native: stub config model for', key)
                return _Stub()
        cls.getConfigModel = getConfigModel
        log('native: ServerSettings.getConfigModel patched')
    except Exception:
        logExc('patch server settings')


AVATAR_DEFAULTS = {
    'name': 'Player', 'sessionID': 'sandbox', 'arenaUniqueID': 1, 'arenaTypeID': 0,
    'arenaBonusType': 2, 'arenaGuiType': 2, 'arenaExtraData': {}, 'weatherPresetID': 0,
    'denunciationsLeft': 0, 'clientCtx': '', 'tkillIsSuspected': False,
    'team': 1, 'playerVehicleID': 0, 'isObserverBothTeams': False, 'observableTeamID': 0,
    'isGunLocked': False, 'ownVehicleGear': 0, 'ownVehicleAuxPhysicsData': 0,
    'ownVehicleHullAimingPitchPacked': 0, 'customizationDisplayType': 0,
    'playLimits': {'curfew': 0, 'weeklyPlayLimit': 0, 'dailyPlayLimit': 0, 'sessionLimit': 0},
    'battleChatRestriction': {'isBattleChatDisabled': False, 'restrictionReasonID': 0},
    'goodiesSnapshot': [], 'shouldSendKillcamSimulationData': False,
    'remoteCamera': {'time': 0.0, 'shotPoint': Math.Vector3(0, 0, 0), 'zoom': 0, 'mode': 0},
    'isObserverFPV': False, 'numOfObservers': 0,
}
VEHICLE_DEFAULTS = {
    'arenaTypeID': 0, 'arenaUniqueID': 1, 'arenaBonusType': 2,
    'remoteCamera': {'time': 0.0, 'shotPoint': Math.Vector3(0, 0, 0), 'zoom': 0, 'mode': 0},
}


def _setClassDefaults(cls, values):
    for k, v in values.items():
        try:
            setattr(cls, k, v)
        except Exception:
            logExc('class default %s.%s' % (cls.__name__, k))


# --------------------------------------------------------------------------- mailboxes
class _Mailbox(object):
    """Stands in for a server mailbox (entity.cell / entity.base)."""

    def __init__(self, server, owner, kind):
        self._server = server
        self._owner = owner
        self._kind = kind

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        server, owner, kind = self._server, self._owner, self._kind

        def remoteCall(*args, **kwargs):
            try:
                return server.onRemoteCall(owner, kind, name, args)
            except Exception:
                logExc('remote %s.%s' % (kind, name))
        return remoteCall


def _installMailboxes(server):
    import Avatar
    import Vehicle
    for cls in (Avatar.PlayerAvatar, Vehicle.Vehicle):
        cls.cell = property(lambda ent: _Mailbox(server, ent, 'cell'))
        cls.base = property(lambda ent: _Mailbox(server, ent, 'base'))
    log('native: mailboxes installed on PlayerAvatar and Vehicle')


# --------------------------------------------------------------------------- simple kinematic body
class Body(object):
    """Movement simulation for one vehicle; the result is fed to the vehicle's filter."""

    def __init__(self, server, vDesc, pos, yaw):
        self.server = server
        self.vDesc = vDesc
        self.pos = Math.Vector3(pos)
        self.yaw = yaw
        self.pitch = 0.0
        self.roll = 0.0
        self.speed = 0.0
        self.yawRate = 0.0
        self.throttle = 0.0
        self.steer = 0.0
        self.maxFwd = vDesc.type.speedLimits[0]
        self.maxBack = vDesc.type.speedLimits[1]
        self.rotSpeed = vDesc.chassis.rotationSpeed
        try:
            cp = vDesc.chassis.topRightCarryingPoint
            self.halfWid = max(1.2, cp[0] + 0.35)
            self.halfLen = max(2.0, cp[1] + 0.6)
        except Exception:
            self.halfWid, self.halfLen = 1.6, 3.0

    def setFlags(self, flags):
        f = 0.0
        if flags & 1:
            f += 1.0
        if flags & 2:
            f -= 1.0
        s = 0.0
        if flags & 4:
            s -= 1.0
        if flags & 8:
            s += 1.0
        self.throttle, self.steer = f, s

    def tick(self, dt):
        sid = self.server.spaceID
        target = self.throttle * (self.maxFwd if self.throttle >= 0 else self.maxBack)
        accel = (self.maxFwd / 3.5) if abs(target) > abs(self.speed) else (self.maxFwd / 1.2)
        if self.speed < target:
            self.speed = min(target, self.speed + accel * dt)
        else:
            self.speed = max(target, self.speed - accel * dt)
        k = 1.0 - 0.35 * abs(self.speed) / max(self.maxFwd, 1.0)
        dyaw = self.steer * self.rotSpeed * k * dt
        self.yaw += dyaw
        self.yawRate = dyaw / dt if dt > 0 else 0.0
        fwd = V3(math.sin(self.yaw), 0, math.cos(self.yaw))
        newPos = self.pos + fwd * (self.speed * dt)
        if abs(self.speed) > 0.05:
            sign = 1.0 if self.speed > 0 else -1.0
            a = self.pos + V3(0, 1.3, 0)
            b = newPos + fwd * (sign * (self.halfLen + 0.3)) + V3(0, 1.3, 0)
            if S.collideStatic(sid, a, b) is not None:
                self.speed = 0.0
                newPos = self.pos
        bb = self.server.bounds
        newPos.x = S.clamp(newPos.x, bb[0] + 5, bb[2] - 5)
        newPos.z = S.clamp(newPos.z, bb[1] + 5, bb[3] - 5)
        h = S.groundHeight(sid, newPos.x, newPos.z, self.pos.y)
        if h is not None:
            newPos.y = h
        self.pos = newPos
        # slope
        right = V3(fwd.z, 0, -fwd.x)
        p = self.pos

        def gh(x, z):
            v = S.groundHeight(sid, x, z, p.y)
            return p.y if v is None else v
        hf = gh(p.x + fwd.x * self.halfLen, p.z + fwd.z * self.halfLen)
        hb = gh(p.x - fwd.x * self.halfLen, p.z - fwd.z * self.halfLen)
        hr = gh(p.x + right.x * self.halfWid, p.z + right.z * self.halfWid)
        hl = gh(p.x - right.x * self.halfWid, p.z - right.z * self.halfWid)
        self.pitch = math.atan2(hb - hf, 2 * self.halfLen)
        self.roll = math.atan2(hl - hr, 2 * self.halfWid)


# --------------------------------------------------------------------------- server
class NativeServer(object):

    def __init__(self, cfg):
        self.cfg = cfg
        self.spaceID = None
        self.avatar = None
        self.avatarID = None
        self.vehicles = {}        # vehID -> dict(body, vDesc, team, health, maxHealth, name, isPlayer, ...)
        self.ownVehID = None
        self.unknownCalls = set()
        self.started = False
        self.lastTime = None
        self.shotID = 0
        self.shells = []
        self.bounds = (-500.0, -500.0, 500.0, 500.0)
        self.step = 'init'

    # ---------------- logging helpers
    def mark(self, step):
        self.step = step
        log('native step:', step)

    # ---------------- remote calls from the client
    def onRemoteCall(self, owner, kind, name, args):
        handler = getattr(self, 'rc_' + name, None)
        if handler is not None:
            return handler(owner, *args)
        key = kind + '.' + name
        if key not in self.unknownCalls:
            self.unknownCalls.add(key)
            log('native: unhandled remote call', key, 'args', repr(args)[:200])
        return None

    def rc_switchObserverFPV(self, owner, *args):
        return None

    def rc_bindToVehicle(self, owner, *args):
        return None

    def rc_vehicle_moveWith(self, owner, flags):
        v = self.vehicles.get(self.ownVehID)
        if v is not None:
            v['body'].setFlags(flags)

    def rc_vehicle_shoot(self, owner):
        self.shoot(self.ownVehID)

    def rc_setClientReady(self, owner):
        self.mark('client ready')
        self.sendPeriod()

    def rc_vehicle_changeSetting(self, owner, code, value):
        try:
            self.avatar.updateVehicleSetting(self.ownVehID, code, value)
        except Exception:
            logExc('updateVehicleSetting')
        if code == 0:  # CURRENT_SHELLS
            v = self.vehicles.get(self.ownVehID)
            if v is not None:
                v['shellCD'] = value
                self.startReload(self.ownVehID)

    # ---------------- startup
    def launch(self):
        self.mark('launch v' + VERSION)
        cfg = self.cfg
        mapName = cfg['map']
        import ArenaType
        cands = [a for a in ArenaType.g_cache.values() if a.geometryName == mapName]
        ctf = [a for a in cands if a.gameplayName == 'ctf']
        arenaType = (ctf or cands or [None])[0]
        if arenaType is None:
            log('native: arena type not found for', mapName)
            return
        self.arenaType = arenaType
        bb = arenaType.boundingBox
        self.bounds = (bb[0][0], bb[0][1], bb[1][0], bb[1][1])
        _installMailboxes(self)
        _patchServerSettings()
        import Avatar
        import Vehicle
        AVATAR_DEFAULTS['arenaTypeID'] = arenaType.id
        VEHICLE_DEFAULTS['arenaTypeID'] = arenaType.id
        _setClassDefaults(Avatar.PlayerAvatar, AVATAR_DEFAULTS)
        _setClassDefaults(Vehicle.Vehicle, VEHICLE_DEFAULTS)
        # space
        BigWorld.clearAllSpaces()
        BigWorld.worldDrawEnabled(False)
        space = BigWorld.createSpace()
        self.space = space
        self.spaceID = space.id
        mask = -1
        try:
            from SpaceVisibilityFlags import SpaceVisibilityFlagsFactory
            mask = SpaceVisibilityFlagsFactory.create('spaces/' + mapName).getMaskForGameplayID('ctf')
        except Exception:
            mask = -1
        BigWorld.addSpaceGeometryMapping(self.spaceID, None, 'spaces/' + mapName, mask, '')
        self.mark('space created %d' % self.spaceID)
        # spawn points
        sp = [[], []]
        try:
            for i in (0, 1):
                sp[i] = [V3(p[0], 0, p[1]) for p in arenaType.teamSpawnPoints[i]]
        except Exception:
            pass
        x0, z0, x1, z1 = self.bounds
        if not sp[0]:
            sp[0] = [V3((x0 + x1) / 2, 0, z0 + (z1 - z0) * 0.15)]
        if not sp[1]:
            sp[1] = [V3((x0 + x1) / 2, 0, z1 - (z1 - z0) * 0.15)]
        self.spawns = sp
        # avatar
        from constants import ARENA_GUI_TYPE, ARENA_BONUS_TYPE
        props = {
            'name': 'Player', 'arenaUniqueID': 1, 'arenaTypeID': arenaType.id,
            'arenaBonusType': ARENA_BONUS_TYPE.TRAINING, 'arenaGuiType': ARENA_GUI_TYPE.TRAINING,
            'arenaExtraData': {}, 'weatherPresetID': 0, 'team': 1, 'playerVehicleID': 0,
        }
        p0 = sp[0][0]
        self.avatarID = BigWorld.createEntity('Avatar', self.spaceID, 0, V3(p0.x, 50, p0.z), (0, 0, 0), props)
        avatar = BigWorld.entity(self.avatarID)
        self.avatar = avatar
        self.mark('avatar entity created %s' % self.avatarID)
        for k, v in props.items():
            try:
                if getattr(avatar, k, None) != v:
                    setattr(avatar, k, v)
            except Exception:
                logExc('avatar prop ' + k)
        BigWorld.player(avatar)
        self.mark('avatar became player; arena=%r' % (getattr(avatar, 'arena', None),))
        BigWorld.callback(0.5, self.__afterPlayer)

    def __afterPlayer(self):
        try:
            self.__createVehicles()
        except Exception:
            logExc('createVehicles')
        self.lastTime = BigWorld.time()
        BigWorld.callback(0.0, self.__tick)
        BigWorld.callback(1.0, self.__waitSpace)

    def __waitSpace(self):
        try:
            status = BigWorld.spaceLoadStatus()
        except Exception:
            status = 1.0
        if status < 0.999:
            BigWorld.callback(0.5, self.__waitSpace)
            return
        self.mark('space loaded')
        self.__placeOnGround()
        if self.step != 'client ready':
            # the GUI may wait for this; send period anyway so the battle can start
            self.sendPeriod()

    def __placeOnGround(self):
        for vid, v in self.vehicles.items():
            b = v['body']
            p = S.collideStatic(self.spaceID, V3(b.pos.x, 1000, b.pos.z), V3(b.pos.x, -500, b.pos.z))
            if p is not None:
                b.pos.y = p.y

    def __vehInfo(self, vid, v):
        return {
            'vehicleID': vid, 'isAlive': True, 'outfitCD': '', 'compDescr': v['compDescr'],
            'fakeName': v['name'], 'name': v['name'], 'team': v['team'], 'isAvatarReady': True,
            'isTeamKiller': False, 'accountDBID': (1 if v['isPlayer'] else 0), 'clanAbbrev': '', 'clanDBID': 0,
            'prebattleID': 0, 'isPrebattleCreator': False, 'forbidInBattleInvitations': True, 'igrType': 0,
            'avatarSessionID': ('player' if v['isPlayer'] else ''), 'overriddenBadge': 0,
            'customRoleSlotTypeId': 0, 'botDisplayStatus': 0, 'teamPanelMode': 0,
            'maxHealth': v['maxHealth'], 'prestigeLevel': 0, 'prestigeGradeMarkID': 0,
            'vehPostProgression': [], 'personalMissionIDs': [], 'personalMissionInfo': {}, 'events': {},
            'badges': ((), ()), 'ranked': (0, 0), 'deathInfo': None, 'respawnID': 0, 'stFrags': 0,
            'frags': 0, 'activePetID': 0, 'tkills': 0, 'fogOfWar': 0, 'position': (0, 0, 0),
        }

    def __createVehicles(self):
        from items import vehicles as iv
        cfg = self.cfg
        p1, p2 = self.spawns[0][0], self.spawns[1][0]
        face = math.atan2(p2.x - p1.x, p2.z - p1.z)
        plan = [(cfg['tank'], 1, p1, face, True)]
        nBots = int(cfg.get('bots', 6))
        nAllies = int(cfg.get('allies', 0))
        pool = list(S.BOT_POOL)
        for i in range(nAllies):
            a = (i + 1) * 1.1
            plan.append((random.choice(pool), 1, p1 + V3(math.cos(a) * 15, 0, math.sin(a) * 15), face, False))
        for i in range(nBots):
            base = self.spawns[1][i % len(self.spawns[1])]
            a = i * 1.3
            r = 0 if i < len(self.spawns[1]) else 15
            plan.append((random.choice(pool), 2, base + V3(math.cos(a) * r, 0, math.sin(a) * r), face + math.pi, False))
        infos = []
        for idx, (typeName, team, pos, yaw, isPlayer) in enumerate(plan):
            try:
                nid, iid = iv.g_list.getIDsByName(typeName)
                vDesc = iv.VehicleDescr(typeID=(nid, iid))
                compDescr = vDesc.makeCompactDescr()
                name = 'Player' if isPlayer else ('Bot_%d' % idx)
                maxHealth = int(vDesc.maxHealth)
                publicInfo = {'name': name, 'compDescr': compDescr, 'outfit': '', 'outfitLevel': 0,
                              'index': idx, 'team': team, 'prebattleID': 0, 'marksOnGun': 0, 'crewGroups': [],
                              'commanderSkinID': 0, 'maxHealth': maxHealth, 'respawnID': 0, 'stFrags': 0}
                h = S.collideStatic(self.spaceID, V3(pos.x, 1000, pos.z), V3(pos.x, -500, pos.z))
                pos = V3(pos.x, h.y if h is not None else 0, pos.z)
                vprops = {'publicInfo': publicInfo, 'health': maxHealth, 'isCrewActive': True,
                          'avatarID': (self.avatarID if isPlayer else 0), 'isMyVehicle': isPlayer,
                          'arenaTypeID': self.arenaType.id, 'arenaUniqueID': 1, 'arenaBonusType': self.avatar.arenaBonusType}
                vid = BigWorld.createEntity('Vehicle', self.spaceID, 0, pos, (0, 0, yaw), vprops)
                v = {'id': vid, 'vDesc': vDesc, 'compDescr': compDescr, 'team': team, 'name': name,
                     'isPlayer': isPlayer, 'health': maxHealth, 'maxHealth': maxHealth, 'alive': True,
                     'body': Body(self, vDesc, pos, yaw), 'reloadLeft': 2.0, 'shellCD': vDesc.shot.shell.compactDescr}
                self.vehicles[vid] = v
                infos.append(self.__vehInfo(vid, v))
                if isPlayer:
                    self.ownVehID = vid
                log('native: vehicle entity', vid, typeName, 'team', team)
            except Exception:
                logExc('create vehicle ' + typeName)
        self.mark('vehicles created: %d' % len(self.vehicles))
        try:
            self.avatar.arena.updateVehiclesList(infos)
            self.mark('arena vehicle list sent')
        except Exception:
            logExc('updateVehiclesList')
        try:
            self.avatar.playerVehicleID = self.ownVehID
            self.avatar.set_playerVehicleID(0)
            self.mark('playerVehicleID set %s' % self.ownVehID)
        except Exception:
            logExc('set_playerVehicleID')
        self.__sendAmmo(self.ownVehID)

    def __sendAmmo(self, vid):
        v = self.vehicles.get(vid)
        if v is None:
            return
        try:
            gun = v['vDesc'].gun
            total = int(getattr(gun, 'maxAmmo', 50))
            shots = list(gun.shots)
            shares = {1: [1.0], 2: [0.7, 0.3], 3: [0.6, 0.25, 0.15]}.get(len(shots), [1.0 / len(shots)] * len(shots))
            for i, shot in enumerate(shots):
                cnt = int(round(total * shares[i]))
                self.avatar.updateVehicleAmmo(vid, shot.shell.compactDescr, cnt, 0, 0, 0, 0)
            self.avatar.updateVehicleSetting(vid, 0, shots[0].shell.compactDescr)
            self.mark('ammo sent')
        except Exception:
            logExc('sendAmmo')

    def sendPeriod(self):
        if self.started:
            return
        self.started = True
        try:
            import cPickle as pickle
        except ImportError:
            import pickle
        from constants import ARENA_PERIOD, ARENA_UPDATE
        try:
            now = BigWorld.serverTime()
        except Exception:
            now = BigWorld.time()
        length = 15 * 60
        data = zlib.compress(pickle.dumps((ARENA_PERIOD.BATTLE, now + length, length, None), 2))
        try:
            self.avatar.updateArena(ARENA_UPDATE.PERIOD, data)
            self.mark('period BATTLE sent')
        except Exception:
            logExc('send period')
        self.startReload(self.ownVehID)

    # ---------------- shooting
    def startReload(self, vid):
        v = self.vehicles.get(vid)
        if v is None:
            return
        t = v['vDesc'].gun.reloadTime
        v['reloadLeft'] = t
        if v['isPlayer']:
            try:
                self.avatar.updateVehicleGunReloadTime(vid, t, t)
            except Exception:
                logExc('updateVehicleGunReloadTime')

    def shoot(self, vid):
        v = self.vehicles.get(vid)
        if v is None or not v['alive'] or v['reloadLeft'] > 0:
            return
        ent = BigWorld.entities.get(vid)
        if ent is None:
            return
        d = v['vDesc']
        shot = d.shot
        for s in d.gun.shots:
            if s.shell.compactDescr == v['shellCD']:
                shot = s
        # muzzle & direction from the real gun node
        start, direction = None, None
        try:
            node = ent.appearance.compoundModel.node('HP_gunFire')
            m = Math.Matrix(node)
            start, direction = m.translation, m.applyToAxis(2)
        except Exception:
            b = v['body']
            start = b.pos + V3(0, 2.0, 0)
            direction = V3(math.sin(b.yaw), 0, math.cos(b.yaw))
        direction.normalise()
        if v['isPlayer']:
            try:
                tp = self.avatar.gunRotator.markerInfo[0]
                dd = tp - start
                dd.normalise()
                direction = dd
            except Exception:
                pass
        self.shotID += 1
        velocity = direction * shot.speed
        try:
            ent.showShooting(1, 0, 0)
        except Exception:
            try:
                ent.showShooting(1, 0)
            except Exception:
                logExc('showShooting')
        try:
            shellTypeIdx = 0
            self.avatar.showTracer(vid, self.shotID, False, shot.shell.effectsIndex, getattr(shot.shell, 'prefabEffectsIndex', -1),
                                   shellTypeIdx, shot.shell.caliber, start, velocity, shot.gravity, shot.maxDistance, 0, 0)
        except Exception:
            logExc('showTracer')
        self.shells.append({'id': self.shotID, 'owner': vid, 'pos': Math.Vector3(start), 'vel': Math.Vector3(velocity),
                            'shot': shot, 'travelled': 0.0})
        self.startReload(vid)

    def __traceShell(self, s, a, b):
        sid = self.spaceID
        best = None
        for vid, v in self.vehicles.items():
            if vid == s['owner']:
                continue
            ent = BigWorld.entities.get(vid)
            try:
                res = ent.appearance.collisions.collideAllWorld(a, b)
            except Exception:
                res = None
            if res:
                d0 = min(r[0] for r in res)
                if best is None or d0 < best[0]:
                    best = (d0, vid)
        seg = b - a
        L = seg.length
        dirv = Math.Vector3(seg)
        dirv.normalise()
        sp = S.collideStatic(sid, a, b)
        dStatic = (sp - a).length if sp is not None else None
        if best is not None and (dStatic is None or best[0] <= dStatic):
            self.__hitVehicle(s, best[1], a + dirv * best[0], dirv)
            return True
        if dStatic is not None and dStatic <= L + 0.01:
            self.__explode(s, sp, dirv)
            return True
        return False

    def __explode(self, s, pos, dirv):
        shot = s['shot']
        try:
            self.avatar.explodeProjectile(s['id'], shot.shell.effectsIndex, getattr(shot.shell, 'prefabEffectsIndex', -1), 0, 0,
                                          shot.shell.caliber, pos, dirv, shot.speed, [])
        except Exception:
            logExc('explodeProjectile')
        try:
            self.avatar.stopTracer(s['id'], pos)
        except Exception:
            pass

    def __hitVehicle(self, s, vid, pos, dirv):
        v = self.vehicles[vid]
        shooter = self.vehicles.get(s['owner'])
        self.__explode(s, pos, dirv)
        if not v['alive']:
            return
        dmg = int(s['shot'].shell.armorDamage[0] * random.uniform(0.75, 1.25))
        if shooter is not None and shooter['isPlayer']:
            dmg = int(dmg * float(self.cfg.get('dmg', 2.0)))
        self.setHealth(vid, v['health'] - dmg, s['owner'])

    def setHealth(self, vid, health, attackerID):
        v = self.vehicles[vid]
        old = v['health']
        health = max(0, int(health))
        v['health'] = health
        ent = BigWorld.entities.get(vid)
        try:
            if ent is not None:
                ent.health = health
                ent.onHealthChanged(health, old, attackerID, 0)
        except Exception:
            try:
                ent.onHealthChanged(health, attackerID, 0)
            except Exception:
                logExc('onHealthChanged')
        if v['isPlayer']:
            try:
                self.avatar.updateVehicleHealth(vid, health, 0 if health <= 0 else -1, True, False)
            except Exception:
                logExc('updateVehicleHealth')
        if health <= 0 and v['alive']:
            v['alive'] = False
            try:
                self.avatar.arena.updateVehicleIsAlive(vid, v['compDescr'], vid == self.ownVehID)
            except Exception:
                logExc('updateVehicleIsAlive')
            log('native: vehicle destroyed', vid)

    # ---------------- bots
    def __botTick(self, vid, v, dt):
        own = self.vehicles.get(self.ownVehID)
        if own is None or not v['alive']:
            v['body'].throttle = v['body'].steer = 0
            return
        target = None
        bestD = 1e9
        for oid, o in self.vehicles.items():
            if o['team'] != v['team'] and o['alive']:
                dd = (o['body'].pos - v['body'].pos).length
                if dd < bestD:
                    target, bestD = o, dd
        b = v['body']
        if target is None:
            b.throttle = b.steer = 0
            return
        to = target['body'].pos - b.pos
        want = math.atan2(to.x, to.z)
        diff = S.angleDiff(want, b.yaw)
        b.steer = S.clamp(diff * 2.0, -1, 1)
        b.throttle = 1.0 if bestD > 180 else (0.0 if bestD > 90 else -0.3)
        v.setdefault('aimTimer', random.uniform(1, 3))
        v['aimTimer'] -= dt
        if v['aimTimer'] <= 0 and bestD < 450 and abs(diff) < 0.4 and v['reloadLeft'] <= 0:
            v['aimTimer'] = random.uniform(1.5, 4.0)
            self.shoot(vid)

    # ---------------- main loop
    def __tick(self):
        try:
            now = BigWorld.time()
            dt = S.clamp(now - (self.lastTime or now), 0.0, 0.1)
            self.lastTime = now
            for vid, v in self.vehicles.items():
                if v['reloadLeft'] > 0:
                    v['reloadLeft'] -= dt
                if not v['isPlayer']:
                    self.__botTick(vid, v, dt)
                b = v['body']
                if v['alive']:
                    b.tick(dt)
                ent = BigWorld.entities.get(vid)
                if ent is None:
                    continue
                f = getattr(ent, 'filter', None)
                try:
                    if f is not None and hasattr(f, 'input'):
                        f.input(BigWorld.time(), self.spaceID, 0, b.pos, (0, 0, 0), (b.roll, b.pitch, b.yaw))
                except Exception:
                    if not v.get('filterErr'):
                        v['filterErr'] = True
                        logExc('filter.input %s' % vid)
                try:
                    app = ent.appearance
                    if app is not None:
                        half = b.halfWid
                        app.updateTracksScroll(b.speed + b.yawRate * half, b.speed - b.yawRate * half)
                except Exception:
                    pass
            # shells
            alive = []
            for s in self.shells:
                g = s['shot'].gravity
                nv = s['vel'] - V3(0, g * dt, 0)
                np_ = s['pos'] + (s['vel'] + nv) * (0.5 * dt)
                if self.__traceShell(s, s['pos'], np_):
                    continue
                s['travelled'] += (np_ - s['pos']).length
                s['pos'], s['vel'] = np_, nv
                if s['travelled'] < s['shot'].maxDistance and s['pos'].y > -200:
                    alive.append(s)
            self.shells = alive
        except Exception:
            logExc('native tick')
        BigWorld.callback(0.0, self.__tick)


g_server = None


def start(cfg):
    global g_server
    g_server = NativeServer(cfg)
    try:
        g_server.launch()
    except Exception:
        logExc('native launch (step %s)' % g_server.step)
    return g_server
