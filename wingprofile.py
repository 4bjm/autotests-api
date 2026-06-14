import win32com.client


def get_sldworks_app(visible=True):
    try:
        sw_app = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception:
        sw_app = win32com.client.Dispatch("SldWorks.Application")
    sw_app.Visible = visible
    return sw_app


def build_airfoil_sketch(sw_app, points, chord_mm=200.0, flip_y=True):
    # points: список (x, y) в диапазоне 0..1 по хорде
    # flip_y: SolidWorks ось Y вверх, а профиль часто задают с Y вверх — иногда нужно инвертировать

    model = sw_app.ActiveDoc
    if model is None:
        raise RuntimeError("Нет активного документа SolidWorks")

    # Если открыта сборка — попытаемся работать в первой компоненте (детали)
    target_model = model
    try:
        is_assembly = (model.GetType == 2)
    except Exception:
        is_assembly = False

    if is_assembly:
        comps = model.GetComponents(True)
        if not comps:
            raise RuntimeError("Сборка не содержит компонентов")

        part_model = None
        for comp in comps:
            try:
                part_model = comp.GetModelDoc2()
            except Exception:
                part_model = None
            if part_model is not None:
                break

        if part_model is None:
            # Попытка открыть первый компонент по пути
            comp0 = comps[0]
            path = comp0.GetPathName
            if not path:
                raise RuntimeError("Первый компонент не имеет пути. Откройте деталь вручную и повторите.")
            # Try opening component document. Prefer OpenDoc6, but fall back to OpenDoc if needed.
            try:
                # OpenDoc6: (fileName, docType(1=part), options, configuration, errors, warnings)
                sw_app.OpenDoc6(path, 1, 0, "", 0, 0)
            except Exception:
                try:
                    # Some SolidWorks versions expose OpenDoc which is simpler
                    sw_app.OpenDoc(path, 1)
                except Exception as e:
                    raise RuntimeError(f"Не удалось открыть документ компонента: {path}. Ошибка: {e}")

            part_model = sw_app.ActiveDoc
            if part_model is None:
                raise RuntimeError(f"Не удалось открыть документ компонента: {path}")

        target_model = part_model

    # Небольшое удобство — начинать из состояния без активных эскизов
    target_model.ClearSelection2(True)

    # Попытки найти плоскость Front Plane (учитываем локализацию и варианты)
    front_plane = None
    try:
        front_plane = target_model.FeatureByName("Front Plane")
    except Exception:
        front_plane = None

    if front_plane is None:
        try:
            front_plane = target_model.FeatureByName("Плоскость спереди")
        except Exception:
            front_plane = None

    if front_plane is None:
        # Поиск по типу признака (искать первую плоскость)
        try:
            feat = target_model.FirstFeature()
            while feat:
                try:
                    tname = feat.GetTypeName2()
                except Exception:
                    tname = None
                if tname and ("Plane" in tname or "RefPlane" in tname or "Плоскость" in tname):
                    front_plane = feat
                    break
                feat = feat.GetNextFeature()
        except Exception:
            front_plane = None

    # Если все ещё не найдена — попробуем выбрать плоскость по SelectByID2 (варианты имён)
    if front_plane is None:
        try:
            part_title = target_model.GetTitle
        except Exception:
            part_title = None
        candidates = [
            "Front Plane",
            f"Front Plane@{part_title}" if part_title else None,
            "Плоскость спереди",
            f"Плоскость спереди@{part_title}" if part_title else None,
        ]
        for name in [c for c in candidates if c]:
            try:
                ok = target_model.Extension.SelectByID2(name, "PLANE", 0, 0, 0, False, 0, None, 0)
            except Exception:
                ok = False
            if ok:
                front_plane = True
                break

    # Если плоскость выбрана как объект Feature, используем Select2
    if hasattr(front_plane, 'Select2') and callable(getattr(front_plane, 'Select2')):
        front_plane.Select2(False, 0)
    elif front_plane is True:
        # уже выбран через SelectByID2
        pass
    else:
        # Попытка без явного выбора: вставить эскиз — иногда работает, если активна плоскость
        try:
            target_model.SketchManager.InsertSketch(True)
        except Exception:
            raise RuntimeError("Не найден 'Front Plane' в целевой детали")

    # true/1 — начать новый эскиз (если не был вызван ранее via SelectByID2)
    # Если мы уже вставили эскиз выше, второй вызов может закрыть его, поэтому проверяем
    try:
        target_model.SketchManager.InsertSketch(True)
    except Exception:
        # игнорируем: это может означать, что эскиз уже открыт/закрыт
        pass

    # Масштабируем и, при необходимости, инвертируем профиль по Y
    scaled_pts = []
    for x, y in points:
        X = x * chord_mm
        Y = y * chord_mm * (-1 if flip_y else 1)
        scaled_pts.append((X, Y))

    # SolidWorks API: создаём сплайн по массиву точек
    # SketchManager.CreateSpline(pointsArray)
    # массив — одномерный: [x1, y1, z1, x2, y2, z2, ...], единицы — метры
    coord_data = []
    for X, Y in scaled_pts:
        coord_data.extend([X / 1000.0, Y / 1000.0, 0.0])

    # Вызов CreateSpline с защитой: попытаться передать массив как VARIANT, иначе создать набор отрезков
    sk_manager = target_model.SketchManager
    spline = None
    try:
        # Создаём VARIANT-массив из python list для COM (массив R8)
        import pythoncom
        from win32com.client import VARIANT
        arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, coord_data)
        try:
            spline = sk_manager.CreateSpline(arr)
        except Exception:
            # иногда метод требует простого списка
            spline = sk_manager.CreateSpline(coord_data)
    except Exception:
        spline = None

    # Если CreateSpline недоступен, рисуем полилинию из отрезков как запасной вариант
    if spline is None:
        try:
            # coord_data: [x1,y1,z1,x2,y2,z2,...]
            pts = [coord_data[i:i+3] for i in range(0, len(coord_data), 3)]
            prev = None
            for p in pts:
                x, y, z = p
                if prev is None:
                    prev = (x, y, z)
                    continue
                sk_manager.CreateLine(prev[0], prev[1], prev[2], x, y, z)
                prev = (x, y, z)
        except Exception:
            # если и это не сработало — выбрасываем ошибку для отладки
            raise RuntimeError("Не удалось создать сплайн или полилинию в эскизе")

    # Можно добавить хорду как опорную линию (0,0)–(chord,0)
    try:
        sk_manager.CreateLine(0.0, 0.0, 0.0, chord_mm / 1000.0, 0.0, 0.0)
    except Exception:
        # ignore if fails
        pass

    # Завершаем эскиз
    try:
        target_model.SketchManager.InsertSketch(True)
    except Exception:
        pass

    return spline


def main():
    # Пример профиля — грубо набор точек (здесь просто пример, подставите свои данные)
    # В реальном случае вы либо генерируете NACA, либо читаете CSV с координатами [web:55].
    airfoil_points = [
        (0.0, 0.0),
        (0.1, 0.04),
        (0.3, 0.06),
        (0.5, 0.05),
        (0.7, 0.03),
        (0.9, 0.01),
        (1.0, 0.0),
        (0.9, -0.01),
        (0.7, -0.03),
        (0.5, -0.05),
        (0.3, -0.06),
        (0.1, -0.04),
        (0.0, 0.0),
    ]

    sw_app = get_sldworks_app()
    build_airfoil_sketch(sw_app, airfoil_points, chord_mm=200.0, flip_y=False)


if __name__ == "__main__":
    main()