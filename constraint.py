from collections import namedtuple
import FreeCAD, FreeCADGui
from . import utils, gui
from .utils import objName,cstrlogger as logger, guilogger
from .proxy import ProxyType, PropertyInfo, propGet, propGetValue

import os
_iconPath = os.path.join(utils.iconPath,'constraints')

def _p(solver,partInfo,subname,shape):
    'return a handle of a transformed point derived from "shape"'
    if not solver:
        if utils.hasCenter(shape):
            return
        return 'a vertex or circular edge/face'
    key = subname+'.p'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        v = utils.getElementPos(shape)
        system.NameTag = key
        e = system.addPoint3dV(*v)
        system.NameTag = partInfo.PartName + '.' + key
        h = system.addTransform(e,*partInfo.Params,group=partInfo.Group)
        system.log('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h

def _n(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed normal quaterion derived from shape'
    if not solver:
        if utils.isPlanar(shape):
            return
        return 'an edge or face with a surface normal'
    key = subname+'.n'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        h = []

        rot = utils.getElementRotation(shape)
        system.NameTag = key
        e = system.addNormal3dV(*utils.getNormal(rot))
        nameTag = partInfo.PartName + '.' + key
        system.NameTag = nameTag
        h.append(system.addTransform(e,*partInfo.Params,group=partInfo.Group))

        # also add x axis pointing quaterion for convenience
        rot = FreeCAD.Rotation(FreeCAD.Vector(0,1,0),90).multiply(rot)
        system.NameTag = key + 'x'
        e = system.addNormal3dV(*utils.getNormal(rot))
        system.NameTag = nameTag + 'x'
        h.append(system.addTransform(e,*partInfo.Params,group=partInfo.Group))

        system.log('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h if retAll else h[0]

def _l(solver,partInfo,subname,shape,retAll=False):
    'return a pair of handle of the end points of an edge in "shape"'
    if not solver:
        if utils.isLinearEdge(shape):
            return
        return 'a linear edge'
    key = subname+'.l'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        system.NameTag = key
        v = shape.Edges[0].Vertexes
        p1 = system.addPoint3dV(*v[0].Point)
        p2 = system.addPoint3dV(*v[-1].Point)
        nameTag = partInfo.PartName + '.' + key
        system.NameTag = nameTag + '.p1'
        tp1 = system.addTransform(p1,*partInfo.Params,group=partInfo.Group)
        system.NameTag = nameTag + '.p2'
        tp2 = system.addTransform(p2,*partInfo.Params,group=partInfo.Group)
        system.NameTag = nameTag
        h = system.addLineSegment(tp1,tp2,group=partInfo.Group)
        h = (h,tp1,tp2,p1,p2)
        system.log('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h if retAll else h[0]

def _ln(solver,partInfo,subname,shape,retAll=False):
    'return a handle for either a line or a normal depends on the shape'
    if not solver:
        if utils.isLinearEdge(shape) or utils.isPlanar(shape):
            return
        return 'a linear edge or edge/face with planar surface'
    if utils.isLinearEdge(shape):
        return _l(solver,partInfo,subname,shape,retAll)
    return _n(solver,partInfo,subname,shape)

def _w(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed plane/workplane from "shape"'
    if not solver:
        if utils.isPlanar(shape):
            return
        return 'an edge/face with a planar surface'

    key = subname+'.w'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        p = _p(solver,partInfo,subname,shape)
        n = _n(solver,partInfo,subname,shape,True)
        system.NameTag = partInfo.PartName + '.' + key
        h = system.addWorkplane(p,n[0],group=partInfo.Group)
        h = [h,p] + n
        system.log('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h if retAll else h[0]

def _wa(solver,partInfo,subname,shape):
    return _w(solver,partInfo,subname,shape,True)

def _c(solver,partInfo,subname,shape,requireArc=False):
    'return a handle of a transformed circle/arc derived from "shape"'
    if not solver:
        r = utils.getElementCircular(shape)
        if r:
            return
        return 'an cicular edge'
    if requireArc:
        key = subname+'.a'
    else:
        key = subname+'.c'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}'.format(key,h))
    else:
        w,p,n,_ = _w(solver,partInfo,subname,shape,True)
        r = utils.getElementCircular(shape)
        if not r:
            raise RuntimeError('shape is not cicular')
        if requireArc or isinstance(r,(list,tuple)):
            l = _l(solver,partInfo,subname,shape,True)
            system.NameTag = partInfo.PartName + '.' + key
            h = system.addArcOfCircle(w,p,l[1],l[2],group=partInfo.Group)
        else:
            nameTag = partInfo.PartName + '.' + key
            system.NameTag = nameTag + '.r'
            hr = system.addDistanceV(r)
            system.NameTag = nameTag
            h = system.addCircle(p,n,hr,group=partInfo.Group)
        system.log('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h

def _a(solver,partInfo,subname,shape):
    'return a handle of a transformed arc derived from "shape"'
    return _c(solver,partInfo,subname,shape,True)


class ConstraintCommand:
    _menuGroupName = ''

    def __init__(self,tp):
        self.tp = tp
        self._id = 100 + tp._id
        self._active = None

    @property
    def _toolbarName(self):
        return self.tp._toolbarName

    def workbenchActivated(self):
        pass

    def workbenchDeactivated(self):
        self._active = None

    def getContextMenuName(self):
        pass

    def getName(self):
        return 'asm3Add'+self.tp.getName()

    def GetResources(self):
        return self.tp.GetResources()

    def Activated(self):
        from .assembly import AsmConstraint
        guilogger.report('constraint "{}" command exception'.format(
            self.tp.getName()), AsmConstraint.make,self.tp._id)

    def IsActive(self):
        if not FreeCAD.ActiveDocument:
            return False
        if self._active is None:
            self.checkActive()
        return self._active

    def checkActive(self):
        from .assembly import AsmConstraint
        if guilogger.catchTrace('selection "{}" exception'.format(
                self.tp.getName()), AsmConstraint.getSelection, self.tp._id):
            self._active = True
        else:
            self._active = False

    def onClearSelection(self):
        self._active = False

class Constraint(ProxyType):
    'constraint meta class'

    _typeID = '_ConstraintType'
    _typeEnum = 'ConstraintType'
    _disabled = 'Disabled'

    @classmethod
    def register(mcs,cls):
        super(Constraint,mcs).register(cls)
        if cls._id>=0 and cls._iconName is not Base._iconName:
            gui.AsmCmdManager.register(ConstraintCommand(cls))

    @classmethod
    def attach(mcs,obj,checkType=True):
        if checkType:
            if not mcs._disabled in obj.PropertiesList:
                obj.addProperty("App::PropertyBool",mcs._disabled,"Base",'')
        return super(Constraint,mcs).attach(obj,checkType)

    @classmethod
    def onChanged(mcs,obj,prop):
        if prop == mcs._disabled:
            obj.ViewObject.signalChangeIcon()
            return
        return super(Constraint,mcs).onChanged(obj,prop)

    @classmethod
    def isDisabled(mcs,obj):
        return getattr(obj,mcs._disabled,False)

    @classmethod
    def check(mcs,tp,group,checkCount=False):
        mcs.getType(tp).check(group,checkCount)

    @classmethod
    def prepare(mcs,obj,solver):
        return mcs.getProxy(obj).prepare(obj,solver)

    @classmethod
    def getFixedParts(mcs,cstrs):
        firstPart = None
        firstPartName = None
        found = False
        ret = set()
        for obj in cstrs:
            cstr = mcs.getProxy(obj)
            if cstr.hasFixedPart(obj):
                found = True
                for info in cstr.getFixedParts(obj):
                    logger.debug('fixed part ' + info.PartName)
                    ret.add(info.Part)

            if not found and not firstPart:
                elements = obj.Proxy.getElements()
                if elements:
                    info = elements[0].Proxy.getInfo()
                    firstPart = info.Part
                    firstPartName = info.PartName

        if not found:
            if not firstPart:
                return None
            logger.debug('lock first part {}'.format(firstPartName))
            ret.add(firstPart)
        return ret

    @classmethod
    def getFixedTransform(mcs,cstrs):
        firstPart = None
        found = False
        ret = {}
        for obj in cstrs:
            cstr = mcs.getProxy(obj)
            if cstr.hasFixedPart(obj):
                for info in cstr.getFixedTransform(obj):
                    found = True
                    ret[info.Part] = info

            if not found and not firstPart:
                elements = obj.Proxy.getElements()
                if elements:
                    info = elements[0].Proxy.getInfo()
                    firstPart = info.Part
        if not found and firstPart:
            ret[firstPart] = False
        return ret

    @classmethod
    def getIcon(mcs,obj):
        cstr = mcs.getProxy(obj)
        if cstr:
            return cstr.getIcon(obj)


def _makeProp(name,tp,doc='',getter=propGet,internal=False):
    PropertyInfo(Constraint,name,tp,doc,getter=getter,
            group='Constraint',internal=internal)

_makeProp('Distance','App::PropertyDistance',getter=propGetValue)
_makeProp('Offset','App::PropertyDistance',getter=propGetValue)
_makeProp('Cascade','App::PropertyBool',internal=True)
_makeProp('Angle','App::PropertyAngle',getter=propGetValue)
_makeProp('LockAngle','App::PropertyBool')
_makeProp('Ratio','App::PropertyFloat')
_makeProp('Difference','App::PropertyFloat')
_makeProp('Diameter','App::PropertyFloat')
_makeProp('Radius','App::PropertyFloat')
_makeProp('Supplement','App::PropertyBool',
        'If True, then the second angle is calculated as 180-angle')
_makeProp('AtEnd','App::PropertyBool',
        'If True, then tangent at the end point, or else at the start point')

_ordinal = ('1st', '2nd', '3rd', '4th', '5th', '6th', '7th')

def cstrName(obj):
    return '{}<{}>'.format(objName(obj),Constraint.getTypeName(obj))


class Base(object):
    __metaclass__ = Constraint
    _id = -1
    _entityDef = ()
    _workplane = False
    _props = []
    _toolbarName = 'Assembly3 Constraints'
    _iconName = 'Assembly_ConstraintGeneral.svg'
    _menuText = 'Create "{}" constraint'

    def __init__(self,_obj):
        pass

    @classmethod
    def getPropertyInfoList(cls):
        return cls._props

    @classmethod
    def constraintFunc(cls,obj,solver):
        try:
            return getattr(solver.system,'add'+cls.getName())
        except AttributeError:
            logger.warn('{} not supported in solver "{}"'.format(
                cstrName(obj),solver.getName()))

    @classmethod
    def getEntityDef(cls,group,checkCount,obj=None):
        entities = cls._entityDef
        if len(group) == len(entities):
            return entities
        if cls._workplane and len(group)==len(entities)+1:
            return list(entities) + [_w]
        if not checkCount and len(group)<len(entities):
            return entities[:len(group)]
        if not obj:
            name = cls.getName()
        else:
            name += cstrName(obj)
        if len(group)<len(entities):
            msg = entities[len(group)](None,None,None,None)
            raise RuntimeError('Constraint {} expects a {} element of '
                '{}'.format(name,_ordinal[len(group)],msg))
        raise RuntimeError('Constraint {} has too many elements, expecting '
            'only {}'.format(name,len(entities)))

    @classmethod
    def check(cls,group,checkCount=False):
        entities = cls.getEntityDef(group,checkCount)
        for i,e in enumerate(entities):
            o = group[i]
            msg = e(None,None,None,o)
            if not msg:
                continue
            if i == len(cls._entityDef):
                raise RuntimeError('Constraint "{}" requires an optional {} '
                    'element to be a planar face for defining a '
                    'workplane'.format(cls.getName(), _ordinal[i], msg))
            raise RuntimeError('Constraint "{}" requires the {} element to be'
                    ' {}'.format(cls.getName(), _ordinal[i], msg))

    @classmethod
    def getIcon(cls,obj):
        return utils.getIcon(cls,Constraint.isDisabled(obj),_iconPath)

    @classmethod
    def getEntities(cls,obj,solver):
        '''maps fcad element shape to entities'''
        elements = obj.Proxy.getElements()
        entities = cls.getEntityDef(elements,True,obj)
        ret = []
        for e,o in zip(entities,elements):
            info = o.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            ret.append(e(solver,partInfo,info.Subname,info.Shape))
        solver.system.log('{} entities: {}'.format(cstrName(obj),ret))
        return ret

    @classmethod
    def prepare(cls,obj,solver):
        func = cls.constraintFunc(obj,solver)
        if func:
            params = cls.getPropertyValues(obj) + cls.getEntities(obj,solver)
            ret = func(*params,group=solver.group)
            solver.system.log('{}: {}'.format(cstrName(obj),ret))
        else:
            logger.warn('{} no constraint func'.format(cstrName(obj)))

    @classmethod
    def hasFixedPart(cls,_obj):
        return False

    @classmethod
    def getMenuText(cls):
        return cls._menuText.format(cls.getName())

    @classmethod
    def getToolTip(cls):
        tooltip = getattr(cls,'_tooltip',None)
        if not tooltip:
            return cls.getMenuText()
        return tooltip.format(cls.getName())

    @classmethod
    def GetResources(cls):
        return {'Pixmap':utils.addIconToFCAD(cls._iconName,_iconPath),
                'MenuText':cls.getMenuText(),
                'ToolTip':cls.getToolTip()}


class Locked(Base):
    _id = 0
    _iconName = 'Assembly_ConstraintLock.svg'
    _tooltip = 'Add a "{}" constraint to fix part(s)'

    @classmethod
    def getFixedParts(cls,obj):
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not utils.isVertex(info.Shape) and \
               not utils.isLinearEdge(info.Shape):
                ret.append(info)
        return ret

    Info = namedtuple('AsmCstrTransformInfo', ('Part', 'Shape'))

    @classmethod
    def getFixedTransform(cls,obj):
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not utils.isVertex(info.Shape) and \
               not utils.isLinearEdge(info.Shape):
                ret.append(cls.Info(Part=info.Part,Shape=None))
                continue
            ret.append(cls.Info(Part=info.Part,Shape=info.Shape))
        return ret

    @classmethod
    def hasFixedPart(cls,obj):
        return len(obj.Proxy.getElements())>0

    @classmethod
    def prepare(cls,obj,solver):
        ret = []
        for element in obj.Proxy.getElements():
            info = element.Proxy.getInfo()
            if not utils.isVertex(info.Shape) and \
               not utils.isLinearEdge(info.Shape):
                continue
            if solver.isFixedPart(info):
                logger.warn('redundant locking element "{}" in constraint '
                        '{}'.format(info.Subname,objName(obj)))
                continue
            partInfo = solver.getPartInfo(info)
            system = solver.system
            for i,v in enumerate(info.Shape.Vertexes):
                subname = info.Subname+'.'+str(i)
                system.NameTag = subname + '.tp'
                e1 = system.addPoint3dV(*info.Placement.multVec(v.Point))
                e2 = _p(solver,partInfo,subname,v)
                if i==0:
                    e0 = e1
                    system.NameTag = partInfo.PartName + '.' + info.Subname
                    ret.append(system.addPointsCoincident(
                        e1,e2,group=solver.group))
                else:
                    system.NameTag = info.Subname + 'tl'
                    l = system.addLineSegment(e0,e1)
                    system.NameTag = partInfo.PartName + '.' + info.Subname
                    ret.append(system.addPointOnLine(e2,l,group=solver.group))

        return ret

    @classmethod
    def check(cls,group,_checkCount=False):
        if not all([utils.isElement(o) for o in group]):
            raise RuntimeError('Constraint "{}" requires all children to be '
                    'of element (Vertex, Edge or Face)'.format(cls.getName()))


class BaseMulti(Base):
    _id = -1
    _entityDef = (_wa,)

    @classmethod
    def check(cls,group,_checkCount=False):
        if len(group)<2:
            raise RuntimeError('Constraint "{}" requires at least two '
                'elements'.format(cls.getName()))
        for o in group:
            msg = cls._entityDef[0](None,None,None,o)
            if msg:
                raise RuntimeError('Constraint "{}" requires all the element '
                    'to be of {}'.format(cls.getName()))
        return

    @classmethod
    def prepare(cls,obj,solver):
        func = cls.constraintFunc(obj,solver);
        if not func:
            logger.warn('{} no constraint func'.format(cstrName(obj)))
            return
        parts = set()
        ref = None
        elements = []
        props = cls.getPropertyValues(obj)

        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if info.Part in parts:
                logger.warn('{} skip duplicate parts {}'.format(
                    cstrName(obj),info.PartName))
                continue
            parts.add(info.Part)
            if solver.isFixedPart(info):
                if ref:
                    logger.warn('{} skip more than one fixed part {}'.format(
                        cstrName(obj),info.PartName))
                    continue
                ref = info
                elements.insert(0,e)
            else:
                elements.append(e)
        if len(elements)<=1:
            logger.warn('{} has no effective constraint'.format(cstrName(obj)))
            return
        e0 = None
        ret = []
        for e in elements:
            info = e.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            if not e0:
                e0 = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
            else:
                e = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
                params = props + [e0,e]
                h = func(*params,group=solver.group)
                if isinstance(h,(list,tuple)):
                    ret += list(h)
                else:
                    ret.append(h)
        return ret


class BaseCascade(BaseMulti):
    @classmethod
    def prepare(cls,obj,solver):
        if not getattr(obj,'Cascade',True):
            return super(BaseCascade,cls).prepare(obj,solver)
        func = cls.constraintFunc(obj,solver);
        if not func:
            logger.warn('{} no constraint func'.format(cstrName(obj)))
            return
        props = cls.getPropertyValues(obj)
        prev = None
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not prev or prev.Part==info.Part:
                prev = info
                continue
            prevInfo = solver.getPartInfo(prev)
            e1 = cls._entityDef[0](solver,prevInfo,prev.Subname,prev.Shape)
            partInfo = solver.getPartInfo(info)
            e2 = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
            prev = info
            if solver.isFixedPart(info):
                params = props + [e1,e2]
            else:
                params = props + [e2,e1]
            h = func(*params,group=solver.group)
            if isinstance(h,(list,tuple)):
                ret += list(h)
            else:
                ret.append(h)

        if not ret:
            logger.warn('{} has no effective constraint'.format(cstrName(obj)))
        return ret


class PlaneCoincident(BaseCascade):
    _id = 35
    _iconName = 'Assembly_ConstraintCoincidence.svg'
    _props = ['Cascade','Offset','LockAngle','Angle']
    _tooltip = \
        'Add a "{}" constraint to conincide planes of two or more parts.\n'\
        'The planes are coincided at their centers with an optional distance.'


class PlaneAlignment(BaseCascade):
    _id = 37
    _iconName = 'Assembly_ConstraintAlignment.svg'
    _props = ['Cascade','Offset','LockAngle','Angle']
    _tooltip = 'Add a "{}" constraint to rotate planes of two or more parts\n'\
               'into the same orientation'


class AxialAlignment(BaseMulti):
    _id = 36
    _iconName = 'Assembly_ConstraintAxial.svg'
    _props = ['LockAngle','Angle']
    _tooltip = 'Add a "{}" constraint to align planes of two or more parts.\n'\
        'The planes are aligned at the direction of their surface normal axis.'


class SameOrientation(BaseMulti):
    _id = 2
    _entityDef = (_n,)
    _iconName = 'Assembly_ConstraintOrientation.svg'
    _tooltip = 'Add a "{}" constraint to align planes of two or more parts.\n'\
        'The planes are aligned to have the same orientation (i.e. rotation)'


class MultiParallel(BaseMulti):
    _id = 291
    _entityDef = (_ln,)
    _iconName = 'Assembly_ConstraintMultiParallel.svg'
    _props = ['LockAngle','Angle']
    _tooltip = 'Add a "{}" constraint to make planes or linear edges of two\n'\
               'or more parts parallel.'


class Base2(Base):
    _id = -1
    _toolbarName = 'Assembly3 Constraints2'


class Angle(Base2):
    _id = 27
    _entityDef = (_ln,_ln)
    _workplane = True
    _props = ["Angle","Supplement"]
    _iconName = 'Assembly_ConstraintAngle.svg'
    _tooltip = 'Add a "{}" constraint to set the angle of planes or linear\n'\
               'edges of two parts.'


class Perpendicular(Base2):
    _id = 28
    _entityDef = (_ln,_ln)
    _workplane = True
    _iconName = 'Assembly_ConstraintPerpendicular.svg'
    _tooltip = 'Add a "{}" constraint to make planes or linear edges of two\n'\
               'parts perpendicular.'


class Parallel(Base2):
    _id = -1
    _entityDef = (_ln,_ln)
    _workplane = True
    _iconName = 'Assembly_ConstraintParallel.svg'
    _tooltip = 'Add a "{}" constraint to make planes or linear edges of two\n'\
               'parts parallel.'


class PointsCoincident(Base2):
    _id = 1
    _entityDef = (_p,_p)
    _workplane = True
    _iconName = 'Assembly_ConstraintPointsCoincident.svg'
    _tooltip = 'Add a "{}" constraint to conincide two points.'


class PointInPlane(Base2):
    _id = 3
    _entityDef = (_p,_w)
    _iconName = 'Assembly_ConstraintPointInPlane.svg'
    _tooltip = 'Add a "{}" to constrain a point inside a plane.'


class PointOnLine(Base2):
    _id = 4
    _entityDef = (_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintPointOnLine.svg'
    _tooltip = 'Add a "{}" to constrain a point on to a line.'


class PointsDistance(Base2):
    _id = 5
    _entityDef = (_p,_p)
    _workplane = True
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointsDistance.svg'
    _tooltip = 'Add a "{}" to constrain the distance of two points.'


class PointsProjectDistance(Base2):
    _id = 6
    _entityDef = (_p,_p,_ln)
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointsProjectDistance.svg'
    _tooltip = 'Add a "{}" to constrain the distance of two points\n' \
               'projected on a line.'


class PointPlaneDistance(Base2):
    _id = 7
    _entityDef = (_p,_w)
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointPlaneDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a plane'


class PointLineDistance(Base2):
    _id = 8
    _entityDef = (_p,_l)
    _workplane = True
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a line'


class EqualPointLineDistance(Base2):
    _id = 13
    _entityDef = (_p,_l,_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintEqualPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a\n'\
             'line to be the same as the distance between another point\n'\
             'and line.'


class EqualAngle(Base2):
    _id = 14
    _entityDef = (_ln,_ln,_ln,_ln)
    _workplane = True
    _props = ["Supplement"]
    _iconName = 'Assembly_ConstraintEqualAngle.svg'
    _tooltip='Add a "{}" to equate the angles between two lines or normals.'

class Symmetric(Base2):
    _id = 16
    _entityDef = (_p,_p,_w)
    _workplane = True
    _iconName = 'Assembly_ConstraintSymmetric.svg'
    _tooltip='Add a "{}" constraint to make two points symmetric about a plane.'


class SymmetricHorizontal(Base2):
    _id = 17
    _entityDef = (_p,_p,_w)


class SymmetricVertical(Base2):
    _id = 18
    _entityDef = (_p,_p,_w)


class SymmetricLine(Base2):
    _id = 19
    _entityDef = (_p,_p,_l,_w)
    _iconName = 'Assembly_ConstraintSymmetricLine.svg'
    _tooltip='Add a "{}" constraint to make two points symmetric about a line.'


class PointsHorizontal(Base2):
    _id = 21
    _entityDef = (_p,_p,_w)
    _iconName = 'Assembly_ConstraintPointsHorizontal.svg'
    _tooltip='Add a "{}" constraint to make two points horizontal with each\n'\
             'other when projected onto a plane.'


class PointsVertical(Base2):
    _id = 22
    _entityDef = (_p,_p,_w)
    _iconName = 'Assembly_ConstraintPointsVertical.svg'
    _tooltip='Add a "{}" constraint to make two points vertical with each\n'\
             'other when projected onto a plane.'


class LineHorizontal(Base2):
    _id = 23
    _entityDef = (_l,_w)
    _iconName = 'Assembly_ConstraintLineHorizontal.svg'
    _tooltip='Add a "{}" constraint to make a line segment horizontal when\n'\
             'projected onto a plane.'


class LineVertical(Base2):
    _id = 24
    _entityDef = (_l,_w)
    _iconName = 'Assembly_ConstraintLineVertical.svg'
    _tooltip='Add a "{}" constraint to make a line segment vertical when\n'\
             'projected onto a plane.'

class PointOnCircle(Base2):
    _id = 26
    _entityDef = (_p,_c)
    _iconName = 'Assembly_ConstraintPointOnCircle.svg'
    _tooltip='Add a "{}" to constrain a point on to a clyndrical plane\n' \
             'defined by a cricle.'


class ArcLineTangent(Base2):
    _id = 30
    _entityDef = (_a,_l)
    _props = ["AtEnd"]
    _iconName = 'Assembly_ConstraintArcLineTangent.svg'
    _tooltip='Add a "{}" constraint to make a line tangent to an arc\n'\
             'at the start or end point of the arc.'


class BaseSketch(Base):
    _id = -1
    _toolbarName = 'Assembly3 Sketch Constraints'


class EqualLength(BaseSketch):
    _id = 9
    _entityDef = (_l,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintEqualLength.svg'
    _tooltip='Add a "{}" constraint to make two lines of the same length.'


class LengthRatio(BaseSketch):
    _id = 10
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Ratio"]
    _iconName = 'Assembly_ConstraintLengthRatio.svg'
    _tooltip='Add a "{}" to constrain the length ratio of two lines.'


class LengthDifference(BaseSketch):
    _id = 11
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Difference"]
    _iconName = 'Assembly_ConstraintLengthDifference.svg'
    _tooltip='Add a "{}" to constrain the length difference of two lines.'


class EqualLengthPointLineDistance(BaseSketch):
    _id = 12
    _entityDef = (_p,_l,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintLengthEqualPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a\n' \
             'line to be the same as the length of a another line.'



class EqualLineArcLength(BaseSketch):
    _id = 15
    _entityDef = (_l,_a)
    _workplane = True
    _tooltip='Add a "{}" constraint to make a line of the same length as an arc'


class MidPoint(BaseSketch):
    _id = 20
    _entityDef = (_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintMidPoint.svg'
    _tooltip='Add a "{}" to constrain a point to the middle point of a line.'



class Diameter(BaseSketch):
    _id = 25
    _entityDef = (_c,)
    _prop = ("Diameter",)
    _tooltip='Add a "{}" to constrain the diameter of a circle/arc'


class EqualRadius(BaseSketch):
    _id = 33
    _entityDef = (_c,_c)
    _iconName = 'Assembly_ConstraintEqualRadius.svg'
    _tooltip='Add a "{}" constraint to make two circles/arcs of the same radius'


#  class CubicLineTangent(BaseSketch):
#      _id = 31
#
#
#  class CurvesTangent(BaseSketch):
#      _id = 32


