Attribute VB_Name = "GenerateActivePowderHead"
Option Explicit

' SolidWorks VBA macro for the approved active powder dosing head V0.1.
' Run Main from SolidWorks. The macro creates native SLDPRT, SLDASM,
' SLDDRW, and PDF files in a user-selected output folder.
'
' Machine interface values are assumptions and are marked VERIFY_ON_MACHINE.

Private Const DOC_PART As Long = 1
Private Const DOC_ASSEMBLY As Long = 2
Private Const DOC_DRAWING As Long = 3
Private Const END_BLIND As Long = 0
Private Const SAVE_CURRENT As Long = 0
Private Const SAVE_SILENT As Long = 1
Private Const MATE_COINCIDENT As Long = 0
Private Const MATE_DISTANCE As Long = 5
Private Const ALIGN_CLOSEST As Long = 1

Private Const RESERVOIR_ID_MM As Double = 60#
Private Const RESERVOIR_OD_MM As Double = 66#
Private Const RESERVOIR_WALL_HEIGHT_MM As Double = 50#
Private Const RESERVOIR_TOTAL_HEIGHT_MM As Double = 104#
Private Const CONE_ANGLE_DEG As Double = 65#
Private Const THROAT_ID_MM As Double = 10#
Private Const THROAT_OD_MM As Double = 16#
Private Const SHAFT_OD_MM As Double = 6#
Private Const UPPER_BLADE_RADIUS_MM As Double = 28.5
Private Const LOWER_BLADE_RADIUS_MM As Double = 22#
Private Const VALVE_PLUG_OD_MM As Double = 9.6
Private Const VALVE_STROKE_MM As Double = 4#
Private Const OUTLET_GUIDE_ID_MM As Double = 8#
Private Const OUTLET_GUIDE_OD_MM As Double = 12#
Private Const OUTLET_GUIDE_LENGTH_MM As Double = 25#
Private Const ADAPTER_OD_MM As Double = 80#
Private Const ADAPTER_THICKNESS_MM As Double = 5#
Private Const TARGET_MASS_MIN_MG As Double = 50#
Private Const TARGET_MASS_MAX_MG As Double = 1000#
Private Const TARGET_TOLERANCE_MG As Double = 10#

Private swApp As Object
Private outputRoot As String
Private partsDir As String
Private drawingsDir As String
Private partTemplate As String
Private assemblyTemplate As String
Private drawingTemplate As String

Public Sub Main()
    On Error GoTo Fail

    Set swApp = Application.SldWorks
    If swApp Is Nothing Then Err.Raise vbObjectError + 100, , "SolidWorks is not available."

    outputRoot = PickOutputFolder()
    If Len(outputRoot) = 0 Then Exit Sub

    partsDir = JoinPath(outputRoot, "parts")
    drawingsDir = JoinPath(outputRoot, "drawings")
    EnsureFolder outputRoot
    EnsureFolder partsDir
    EnsureFolder drawingsDir

    partTemplate = ResolveTemplate(DOC_PART)
    assemblyTemplate = ResolveTemplate(DOC_ASSEMBLY)
    drawingTemplate = ResolveTemplate(DOC_DRAWING)

    CreateReservoir
    CreateThroatInsert
    CreateValvePlug
    CreateAgitatorShaft
    CreateUpperBlade
    CreateLowerBlade
    CreateOutletGuide
    CreateMotorBracket
    CreateMachineAdapter
    CreateActiveHeadAssembly
    CreateEngineeringDrawing

    MsgBox "Native SolidWorks files created in:" & vbCrLf & outputRoot & vbCrLf & vbCrLf & _
           "Open the assembly, rebuild all four configurations, and verify the assumed LA10 interface on the machine.", _
           vbInformation, "Active powder dosing head V0.1"
    Exit Sub

Fail:
    MsgBox "Generation stopped: " & Err.Description, vbCritical, "Active powder dosing head V0.1"
End Sub

Private Sub CreateReservoir()
    Dim model As Object
    Set model = NewPartDocument("Reservoir body")

    BeginSketchOnReferencePlane model, 1
    CreateReservoirRevolveProfile model
    EndActiveSketch model
    RevolveFull model
    AddTextProperty model, "CONE_ANGLE_DEG", FormatNumber(CONE_ANGLE_DEG, 1)
    AddTextProperty model, "POWDER_CONTACT", "YES"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "316L or PEEK"
    SavePart model, "reservoir_body_V01.SLDPRT"
End Sub

Private Sub CreateThroatInsert()
    Dim model As Object
    Set model = NewPartDocument("Throat insert")

    BeginSketchOnReferencePlane model, 2
    CreateAnnulus model, THROAT_OD_MM / 2#, THROAT_ID_MM / 2#
    EndActiveSketch model
    BossExtrude model, 12#
    AddTextProperty model, "SEAL_SEAT_DEG", "60"
    AddTextProperty model, "POWDER_CONTACT", "YES"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "316L"
    SavePart model, "throat_insert_V01.SLDPRT"
End Sub

Private Sub CreateValvePlug()
    Dim model As Object
    Set model = NewPartDocument("Axial valve plug")

    BeginSketchOnReferencePlane model, 2
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(VALVE_PLUG_OD_MM / 2#)
    EndActiveSketch model
    BossExtrude model, 34#
    AddTextProperty model, "PTFE_TIP", "60 DEGREE CONICAL SEAL"
    AddTextProperty model, "VALVE_STROKE_MM", CStr(VALVE_STROKE_MM)
    AddTextProperty model, "POWDER_CONTACT", "YES"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "316L shaft with virgin PTFE tip"
    SavePart model, "valve_plug_V01.SLDPRT"
End Sub

Private Sub CreateAgitatorShaft()
    Dim model As Object
    Set model = NewPartDocument("Agitator shaft")

    BeginSketchOnReferencePlane model, 2
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(SHAFT_OD_MM / 2#)
    EndActiveSketch model
    BossExtrude model, 130#
    AddTextProperty model, "NORMAL_SPEED_RPM", "5-30"
    AddTextProperty model, "POWDER_CONTACT", "YES"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "316L"
    SavePart model, "agitator_shaft_V01.SLDPRT"
End Sub

Private Sub CreateUpperBlade()
    Dim model As Object
    Set model = NewPartDocument("Upper flexible blade")

    BeginSketchOnReferencePlane model, 2
    CreateBladeProfile model, UPPER_BLADE_RADIUS_MM, 11#
    EndActiveSketch model
    BossExtrude model, 2#
    AddTextProperty model, "NOMINAL_WALL_CLEARANCE_MM", "1.5"
    AddTextProperty model, "POWDER_CONTACT", "YES"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "PTFE or spring 316L"
    SavePart model, "upper_blade_V01.SLDPRT"
End Sub

Private Sub CreateLowerBlade()
    Dim model As Object
    Set model = NewPartDocument("Lower flexible blade")

    BeginSketchOnReferencePlane model, 2
    CreateBladeProfile model, LOWER_BLADE_RADIUS_MM, 9#
    EndActiveSketch model
    BossExtrude model, 2#
    AddTextProperty model, "NOMINAL_CONE_CLEARANCE_MM", "1.0"
    AddTextProperty model, "POWDER_CONTACT", "YES"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "PTFE or spring 316L"
    SavePart model, "lower_blade_V01.SLDPRT"
End Sub

Private Sub CreateOutletGuide()
    Dim model As Object
    Set model = NewPartDocument("Conductive outlet guide")

    BeginSketchOnReferencePlane model, 2
    CreateAnnulus model, OUTLET_GUIDE_OD_MM / 2#, OUTLET_GUIDE_ID_MM / 2#
    EndActiveSketch model
    BossExtrude model, OUTLET_GUIDE_LENGTH_MM
    AddTextProperty model, "GROUND_OR_CONDUCTIVE", "REQUIRED"
    AddTextProperty model, "POWDER_CONTACT", "YES"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "316L"
    SavePart model, "outlet_guide_V01.SLDPRT"
End Sub

Private Sub CreateMotorBracket()
    Dim model As Object
    Set model = NewPartDocument("Motor bracket")

    BeginSketchOnReferencePlane model, 2
    CreateRectangleLoop model, -30#, -20#, 30#, 20#
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(5#)
    EndActiveSketch model
    BossExtrude model, 4#
    AddTextProperty model, "MOTOR_INTERFACE", "VERIFY_ON_MACHINE"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "6061-T6 or printed nylon prototype"
    SavePart model, "motor_bracket_V01.SLDPRT"
End Sub

Private Sub CreateMachineAdapter()
    Dim model As Object
    Set model = NewPartDocument("LA10 machine adapter")

    BeginSketchOnReferencePlane model, 2
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(ADAPTER_OD_MM / 2#)
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(15#)
    CreateRadialRectangularSlot model, 26#, 0#, 12#, 4.5
    CreateRadialRectangularSlot model, 26#, 120#, 12#, 4.5
    CreateRadialRectangularSlot model, 26#, 240#, 12#, 4.5
    EndActiveSketch model
    BossExtrude model, ADAPTER_THICKNESS_MM
    AddTextProperty model, "LA10_INTERFACE", "VERIFY_ON_MACHINE"
    AddTextProperty model, "ASSUMED_ADAPTER_OD_MM", CStr(ADAPTER_OD_MM)
    AddTextProperty model, "ASSUMED_SLOT_MM", "4.5 x 12, 3 places"
    AddTextProperty model, "MATERIAL_RECOMMENDATION", "6061-T6 or printed nylon prototype"
    SavePart model, "machine_adapter_V01.SLDPRT"
End Sub

Private Sub CreateActiveHeadAssembly()
    Dim model As Object
    Dim assembly As Object
    Dim reservoir As Object
    Dim throat As Object
    Dim valvePlug As Object
    Dim shaft As Object
    Dim upperBlade As Object
    Dim lowerBlade As Object
    Dim outlet As Object
    Dim bracket As Object
    Dim adapter As Object
    Dim valveMate As Object
    Dim assemblyPath As String

    Set model = swApp.NewDocument(assemblyTemplate, DOC_ASSEMBLY, 0#, 0#)
    If model Is Nothing Then Err.Raise vbObjectError + 130, , "Unable to create assembly document."
    Set assembly = model

    Set adapter = assembly.AddComponent5(PartPath("machine_adapter_V01.SLDPRT"), 0, "", False, "", 0#, Mm(-8#), 0#)
    Set reservoir = assembly.AddComponent5(PartPath("reservoir_body_V01.SLDPRT"), 0, "", False, "", 0#, 0#, 0#)
    Set throat = assembly.AddComponent5(PartPath("throat_insert_V01.SLDPRT"), 0, "", False, "", 0#, Mm(-4#), 0#)
    Set outlet = assembly.AddComponent5(PartPath("outlet_guide_V01.SLDPRT"), 0, "", False, "", 0#, Mm(-29#), 0#)
    Set valvePlug = assembly.AddComponent5(PartPath("valve_plug_V01.SLDPRT"), 0, "", False, "", 0#, 0#, 0#)
    Set shaft = assembly.AddComponent5(PartPath("agitator_shaft_V01.SLDPRT"), 0, "", False, "", 0#, Mm(4#), 0#)
    Set upperBlade = assembly.AddComponent5(PartPath("upper_blade_V01.SLDPRT"), 0, "", False, "", 0#, Mm(78#), 0#)
    Set lowerBlade = assembly.AddComponent5(PartPath("lower_blade_V01.SLDPRT"), 0, "", False, "", 0#, Mm(36#), 0#)
    Set bracket = assembly.AddComponent5(PartPath("motor_bracket_V01.SLDPRT"), 0, "", False, "", 0#, Mm(112#), 0#)

    If reservoir Is Nothing Or throat Is Nothing Or valvePlug Is Nothing Then _
        Err.Raise vbObjectError + 131, , "One or more required components could not be inserted."

    adapter.Select4 False, Nothing, False
    assembly.FixComponent
    model.ClearSelection2 True

    ' Origin-plane coincident mates provide coaxial/concentric alignment without
    ' depending on localized feature names or fragile circular-edge coordinates.
    AddConcentricAxisMate assembly, adapter, reservoir, 0#
    AddConcentricAxisMate assembly, reservoir, throat, Mm(-4#)
    AddConcentricAxisMate assembly, throat, outlet, Mm(-25#)
    AddConcentricAxisMate assembly, reservoir, shaft, Mm(4#)
    AddConcentricAxisMate assembly, shaft, upperBlade, Mm(74#)
    AddConcentricAxisMate assembly, shaft, lowerBlade, Mm(32#)
    AddConcentricAxisMate assembly, reservoir, bracket, Mm(112#)
    Set valveMate = AddAxialDistanceMate(assembly, throat, valvePlug, 0#)
    If Not valveMate Is Nothing Then valveMate.Name = "ValveLift"

    AddValveConfiguration model, "CLOSED", 0#, valveMate
    AddValveConfiguration model, "FINE", 0.5, valveMate
    AddValveConfiguration model, "TRANSITION", 1.25, valveMate
    AddValveConfiguration model, "COARSE", 3#, valveMate
    model.ShowConfiguration2 "CLOSED"

    AddTextProperty model, "TARGET_MASS_MG", "50-1000"
    AddTextProperty model, "TARGET_TOLERANCE_MG", "+/-10"
    AddTextProperty model, "LA10_INTERFACE", "VERIFY_ON_MACHINE"
    AddTextProperty model, "MATE_SCHEME", "Origin-plane coincident mates provide concentric axis alignment"

    assemblyPath = JoinPath(outputRoot, "active_powder_head_V01.SLDASM")
    model.ForceRebuild3 False
    SaveModel model, assemblyPath
End Sub

Private Sub CreateEngineeringDrawing()
    Dim model As Object
    Dim drawing As Object
    Dim assemblyPath As String
    Dim drawingPath As String
    Dim pdfPath As String
    Dim noteText As String
    Dim errors As Long
    Dim warnings As Long
    Dim ok As Boolean

    assemblyPath = JoinPath(outputRoot, "active_powder_head_V01.SLDASM")
    drawingPath = JoinPath(drawingsDir, "active_powder_head_V01.SLDDRW")
    pdfPath = JoinPath(drawingsDir, "active_powder_head_V01.pdf")

    Set model = swApp.NewDocument(drawingTemplate, DOC_DRAWING, 0#, 0#)
    If model Is Nothing Then Err.Raise vbObjectError + 140, , "Unable to create drawing document."
    Set drawing = model

    drawing.CreateDrawViewFromModelView3 assemblyPath, "*Front", 0.105, 0.19, 0#
    drawing.CreateDrawViewFromModelView3 assemblyPath, "*Top", 0.105, 0.08, 0#
    drawing.CreateDrawViewFromModelView3 assemblyPath, "*Isometric", 0.235, 0.16, 0#

    noteText = "ACTIVE POWDER DOSING HEAD V0.1" & vbCrLf & _
               "TARGET: " & CStr(TARGET_MASS_MIN_MG) & "-" & CStr(TARGET_MASS_MAX_MG) & " mg, +/-" & CStr(TARGET_TOLERANCE_MG) & " mg" & vbCrLf & _
               "VALVE CONFIGURATIONS: CLOSED 0.00 mm; FINE 0.50 mm; TRANSITION 1.25 mm; COARSE 3.00 mm" & vbCrLf & _
               "THROAT: DIA " & CStr(THROAT_ID_MM) & " mm; VALVE STROKE: " & CStr(VALVE_STROKE_MM) & " mm" & vbCrLf & _
               "VERIFY_ON_MACHINE: LA10 bolt pattern, adapter OD " & CStr(ADAPTER_OD_MM) & " mm, and 3 x 4.5 x 12 mm slots are assumed."
    model.InsertNote noteText

    SaveModel model, drawingPath
    ok = model.Extension.SaveAs(pdfPath, SAVE_CURRENT, SAVE_SILENT, Nothing, errors, warnings)
    If Not ok Then Err.Raise vbObjectError + 141, , "PDF export failed. Error " & CStr(errors) & ", warning " & CStr(warnings)
End Sub

Private Function NewPartDocument(ByVal title As String) As Object
    Dim model As Object
    Set model = swApp.NewDocument(partTemplate, DOC_PART, 0#, 0#)
    If model Is Nothing Then Err.Raise vbObjectError + 110, , "Unable to create part: " & title
    AddTextProperty model, "PART_TITLE", title
    Set NewPartDocument = model
End Function

Private Sub CreateReservoirRevolveProfile(ByVal model As Object)
    Dim sm As Object
    Dim outerRadius As Double
    Dim innerRadius As Double
    Dim throatOuter As Double
    Dim throatInner As Double
    Dim topY As Double
    Dim coneStartY As Double

    Set sm = model.SketchManager
    outerRadius = Mm(RESERVOIR_OD_MM / 2#)
    innerRadius = Mm(RESERVOIR_ID_MM / 2#)
    throatOuter = Mm(THROAT_OD_MM / 2#)
    throatInner = Mm(THROAT_ID_MM / 2#)
    topY = Mm(RESERVOIR_TOTAL_HEIGHT_MM)
    coneStartY = Mm(RESERVOIR_TOTAL_HEIGHT_MM - RESERVOIR_WALL_HEIGHT_MM)

    sm.CreateCenterLine 0#, Mm(-2#), 0#, 0#, Mm(RESERVOIR_TOTAL_HEIGHT_MM + 4#), 0#
    sm.CreateLine throatOuter, 0#, 0#, outerRadius, coneStartY, 0#
    sm.CreateLine outerRadius, coneStartY, 0#, outerRadius, topY, 0#
    sm.CreateLine outerRadius, topY, 0#, innerRadius, topY, 0#
    sm.CreateLine innerRadius, topY, 0#, innerRadius, coneStartY + Mm(1#), 0#
    sm.CreateLine innerRadius, coneStartY + Mm(1#), 0#, throatInner, Mm(3#), 0#
    sm.CreateLine throatInner, Mm(3#), 0#, throatInner, 0#, 0#
    sm.CreateLine throatInner, 0#, 0#, throatOuter, 0#, 0#
End Sub

Private Sub CreateBladeProfile(ByVal model As Object, ByVal radiusMm As Double, ByVal widthMm As Double)
    CreateRectangleLoop model, -5#, -widthMm / 2#, radiusMm, widthMm / 2#
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(3.15)
End Sub

Private Sub CreateAnnulus(ByVal model As Object, ByVal outerRadiusMm As Double, ByVal innerRadiusMm As Double)
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(outerRadiusMm)
    model.SketchManager.CreateCircleByRadius 0#, 0#, 0#, Mm(innerRadiusMm)
End Sub

Private Sub CreateRectangleLoop(ByVal model As Object, ByVal x1Mm As Double, ByVal y1Mm As Double, ByVal x2Mm As Double, ByVal y2Mm As Double)
    Dim sm As Object
    Set sm = model.SketchManager
    sm.CreateLine Mm(x1Mm), Mm(y1Mm), 0#, Mm(x2Mm), Mm(y1Mm), 0#
    sm.CreateLine Mm(x2Mm), Mm(y1Mm), 0#, Mm(x2Mm), Mm(y2Mm), 0#
    sm.CreateLine Mm(x2Mm), Mm(y2Mm), 0#, Mm(x1Mm), Mm(y2Mm), 0#
    sm.CreateLine Mm(x1Mm), Mm(y2Mm), 0#, Mm(x1Mm), Mm(y1Mm), 0#
End Sub

Private Sub CreateRadialRectangularSlot(ByVal model As Object, ByVal radiusMm As Double, ByVal angleDeg As Double, ByVal lengthMm As Double, ByVal widthMm As Double)
    Dim a As Double
    Dim ux As Double
    Dim uy As Double
    Dim vx As Double
    Dim vy As Double
    Dim cx As Double
    Dim cy As Double
    Dim hl As Double
    Dim hw As Double
    Dim x1 As Double, y1 As Double, x2 As Double, y2 As Double
    Dim x3 As Double, y3 As Double, x4 As Double, y4 As Double
    Dim sm As Object

    a = angleDeg * 3.14159265358979# / 180#
    ux = Cos(a): uy = Sin(a)
    vx = -uy: vy = ux
    cx = radiusMm * ux: cy = radiusMm * uy
    hl = lengthMm / 2#: hw = widthMm / 2#
    x1 = cx - hl * ux - hw * vx: y1 = cy - hl * uy - hw * vy
    x2 = cx + hl * ux - hw * vx: y2 = cy + hl * uy - hw * vy
    x3 = cx + hl * ux + hw * vx: y3 = cy + hl * uy + hw * vy
    x4 = cx - hl * ux + hw * vx: y4 = cy - hl * uy + hw * vy

    Set sm = model.SketchManager
    sm.CreateLine Mm(x1), Mm(y1), 0#, Mm(x2), Mm(y2), 0#
    sm.CreateLine Mm(x2), Mm(y2), 0#, Mm(x3), Mm(y3), 0#
    sm.CreateLine Mm(x3), Mm(y3), 0#, Mm(x4), Mm(y4), 0#
    sm.CreateLine Mm(x4), Mm(y4), 0#, Mm(x1), Mm(y1), 0#
End Sub

Private Sub BeginSketchOnReferencePlane(ByVal model As Object, ByVal planeOrdinal As Long)
    Dim planeFeature As Object
    Set planeFeature = GetReferencePlane(model, planeOrdinal)
    If planeFeature Is Nothing Then Err.Raise vbObjectError + 150, , "Reference plane not found."
    planeFeature.Select2 False, 0
    model.SketchManager.InsertSketch True
End Sub

Private Sub EndActiveSketch(ByVal model As Object)
    Dim sketchFeature As Object

    model.SketchManager.InsertSketch True
    model.ClearSelection2 True
    Set sketchFeature = FindLatestSketchFeature(model)
    If sketchFeature Is Nothing Then Err.Raise vbObjectError + 154, , "Finished sketch feature was not found."
    If Not sketchFeature.Select2(False, 0) Then _
        Err.Raise vbObjectError + 155, , "Finished sketch could not be selected."
End Sub

Private Function FindLatestSketchFeature(ByVal model As Object) As Object
    Dim feature As Object
    Dim candidate As Object
    Dim typeName As String

    Set feature = model.FirstFeature
    Do While Not feature Is Nothing
        typeName = LCase$(feature.GetTypeName2)
        If typeName = "profilefeature" Or typeName = "sketch" Then Set candidate = feature
        Set feature = feature.GetNextFeature
    Loop
    Set FindLatestSketchFeature = candidate
End Function

Private Function GetReferencePlane(ByVal model As Object, ByVal planeOrdinal As Long) As Object
    Dim feature As Object
    Dim count As Long
    Set feature = model.FirstFeature
    Do While Not feature Is Nothing
        If LCase$(feature.GetTypeName2) = "refplane" Then
            count = count + 1
            If count = planeOrdinal Then
                Set GetReferencePlane = feature
                Exit Function
            End If
        End If
        Set feature = feature.GetNextFeature
    Loop
End Function

Private Sub BossExtrude(ByVal model As Object, ByVal depthMm As Double)
    Dim feature As Object
    Set feature = model.FeatureManager.FeatureExtrusion2(True, False, False, END_BLIND, END_BLIND, _
        Mm(depthMm), 0#, False, False, False, False, 0#, 0#, False, False, False, False, True, True, True, 0, 0#, False)
    If feature Is Nothing Then Err.Raise vbObjectError + 151, , "Boss extrusion failed."
End Sub

Private Sub RevolveFull(ByVal model As Object)
    Dim feature As Object
    Set feature = model.FeatureManager.FeatureRevolve2(True, True, False, False, False, False, 0, 0, _
        6.28318530717959#, 0#, False, False, 0#, 0#, 0, 0, 0, True, True, True)
    If feature Is Nothing Then Err.Raise vbObjectError + 152, , "Reservoir revolve failed."
End Sub

Private Sub SavePart(ByVal model As Object, ByVal fileName As String)
    model.ForceRebuild3 False
    SaveModel model, PartPath(fileName)
End Sub

Private Sub SaveModel(ByVal model As Object, ByVal fullPath As String)
    Dim errors As Long
    Dim warnings As Long
    Dim ok As Boolean

    If FileExists(fullPath) Then
        If MsgBox("Overwrite existing file?" & vbCrLf & fullPath, vbYesNo Or vbQuestion, "SolidWorks macro") <> vbYes Then _
            Err.Raise vbObjectError + 160, , "Output file already exists: " & fullPath
    End If
    ok = model.Extension.SaveAs(fullPath, SAVE_CURRENT, SAVE_SILENT, Nothing, errors, warnings)
    If Not ok Then Err.Raise vbObjectError + 161, , "Save failed: " & fullPath & " (error " & CStr(errors) & ")"
End Sub

Private Sub AddTextProperty(ByVal model As Object, ByVal propertyName As String, ByVal propertyValue As String)
    Dim manager As Object
    Set manager = model.Extension.CustomPropertyManager("")
    manager.Add3 propertyName, 30, propertyValue, 2
End Sub

Private Sub AddValveConfiguration(ByVal model As Object, ByVal configName As String, ByVal liftMm As Double, ByVal valveMate As Object)
    Dim config As Object
    Dim manager As Object

    Set config = model.ConfigurationManager.AddConfiguration2(configName, "Valve lift configuration", "", 0)
    If config Is Nothing Then Exit Sub
    Set manager = config.CustomPropertyManager
    manager.Add3 "VALVE_LIFT_MM", 30, FormatNumber(liftMm, 2), 2
    SetMateDistanceForConfiguration model, valveMate, configName, liftMm
End Sub

Private Sub SetMateDistanceForConfiguration(ByVal model As Object, ByVal valveMate As Object, ByVal configName As String, ByVal liftMm As Double)
    Dim displayDimension As Object
    Dim dimension As Object

    If valveMate Is Nothing Then Exit Sub
    On Error Resume Next
    model.ShowConfiguration2 configName
    Set displayDimension = valveMate.GetFirstDisplayDimension
    If Not displayDimension Is Nothing Then
        Set dimension = displayDimension.GetDimension2(0)
        If Not dimension Is Nothing Then dimension.SetSystemValue3 Mm(liftMm), 3, Array(configName)
    End If
    On Error GoTo 0
End Sub

Private Sub AddConcentricAxisMate(ByVal assembly As Object, ByVal fixedComponent As Object, ByVal movingComponent As Object, ByVal axialOffsetM As Double)
    ' Two coincident reference-plane mates align the shared longitudinal axis.
    AddCoincidentReferenceMate assembly, fixedComponent, movingComponent, 1
    AddCoincidentReferenceMate assembly, fixedComponent, movingComponent, 3
    If Abs(axialOffsetM) > 0.0000001 Then AddAxialDistanceMate assembly, fixedComponent, movingComponent, axialOffsetM
End Sub

Private Sub AddCoincidentReferenceMate(ByVal assembly As Object, ByVal componentA As Object, ByVal componentB As Object, ByVal planeOrdinal As Long)
    Dim errorStatus As Long
    Dim mateFeature As Object

    assembly.ClearSelection2 True
    If Not SelectComponentPlane(componentA, planeOrdinal, False) Then Exit Sub
    If Not SelectComponentPlane(componentB, planeOrdinal, True) Then Exit Sub
    Set mateFeature = assembly.AddMate3(MATE_COINCIDENT, ALIGN_CLOSEST, False, 0#, 0#, 0#, 0#, 0#, 0#, 0#, 0#, errorStatus)
    assembly.ClearSelection2 True
End Sub

Private Function AddAxialDistanceMate(ByVal assembly As Object, ByVal componentA As Object, ByVal componentB As Object, ByVal distanceM As Double) As Object
    Dim errorStatus As Long
    Dim mateFeature As Object

    assembly.ClearSelection2 True
    If Not SelectComponentPlane(componentA, 2, False) Then Exit Function
    If Not SelectComponentPlane(componentB, 2, True) Then Exit Function
    Set mateFeature = assembly.AddMate3(MATE_DISTANCE, ALIGN_CLOSEST, False, Abs(distanceM), Abs(distanceM), 0#, 0#, 0#, 0#, 0#, 0#, errorStatus)
    assembly.ClearSelection2 True
    Set AddAxialDistanceMate = mateFeature
End Function

Private Function SelectComponentPlane(ByVal component As Object, ByVal planeOrdinal As Long, ByVal appendSelection As Boolean) As Boolean
    Dim partModel As Object
    Dim partPlane As Object
    Dim assemblyPlane As Object

    Set partModel = component.GetModelDoc2
    If partModel Is Nothing Then Exit Function
    Set partPlane = GetReferencePlane(partModel, planeOrdinal)
    If partPlane Is Nothing Then Exit Function
    Set assemblyPlane = component.GetCorresponding(partPlane)
    If assemblyPlane Is Nothing Then Exit Function
    SelectComponentPlane = assemblyPlane.Select2(appendSelection, 0)
End Function

Private Function ResolveTemplate(ByVal documentType As Long) As String
    Dim templatePath As String
    templatePath = swApp.GetDocumentTemplate(documentType, "", 0, 0#, 0#)
    If Len(templatePath) = 0 Then _
        Err.Raise vbObjectError + 170, , "Default SolidWorks template is not configured for document type " & CStr(documentType) & "."
    ResolveTemplate = templatePath
End Function

Private Function PickOutputFolder() As String
    Dim shellObject As Object
    Dim folderObject As Object

    Set shellObject = CreateObject("Shell.Application")
    Set folderObject = shellObject.BrowseForFolder(0, "Choose output folder for native SolidWorks files", 1, 0)
    If folderObject Is Nothing Then Exit Function
    PickOutputFolder = folderObject.Self.Path
End Function

Private Sub EnsureFolder(ByVal folderPath As String)
    If Len(Dir$(folderPath, vbDirectory)) = 0 Then MkDir folderPath
End Sub

Private Function PartPath(ByVal fileName As String) As String
    PartPath = JoinPath(partsDir, fileName)
End Function

Private Function JoinPath(ByVal parentPath As String, ByVal childName As String) As String
    If Right$(parentPath, 1) = "\" Then
        JoinPath = parentPath & childName
    Else
        JoinPath = parentPath & "\" & childName
    End If
End Function

Private Function FileExists(ByVal filePath As String) As Boolean
    FileExists = Len(Dir$(filePath, vbNormal Or vbHidden Or vbSystem Or vbReadOnly)) > 0
End Function

Private Function Mm(ByVal valueMm As Double) As Double
    Mm = valueMm / 1000#
End Function
