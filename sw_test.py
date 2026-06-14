import win32com.client


def get_sldworks_app(visible=True):
    try:
        sw_app = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception:
        sw_app = win32com.client.Dispatch("SldWorks.Application")
    sw_app.Visible = visible
    return sw_app


def main():
    sw_app = get_sldworks_app()
    # Получаем активный документ (деталь/сборка/чертёж)
    model = sw_app.ActiveDoc

    if model is None:
        print("В SolidWorks сейчас нет активного документа.")
        return

    title = model.GetTitle
    doc_type = model.GetType  # 1 — part, 2 — assembly, 3 — drawing и т. д.
    print(f"Активный документ: {title}, тип: {doc_type}")


if __name__ == "__main__":
    main()