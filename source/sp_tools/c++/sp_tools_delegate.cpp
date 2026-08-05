// sp_tools_delegate_qt6.dll
// Substance 3D Painter 属性面板图层工具 —— C++ 界面注入模块（Qt6 / Painter 10.1+）
//
// 职责：
//   * 查找属性面板中的通道按钮（objectName == "channelSelector"）
//   * 在通道按钮行下方注入“每通道 混合模式 + 不透明度”控件面板
//   * 面板被 Painter 重建时自动重新注入（QPointer + 兜底定时器）
//   * 用户改动控件时通过 ctypes 回调通知 Python 写回图层
//
// Python 通过 ctypes 调用本模块：通道/混合模式列表、图层当前值由 Python 下发。

#include <QtCore/QCoreApplication>
#include <QtCore/QEvent>
#include <QtCore/QPointer>
#include <QtCore/QTimer>
#include <QtCore/QVector>
#include <QtWidgets/QApplication>
#include <QtWidgets/QAbstractItemView>
#include <QtWidgets/QBoxLayout>
#include <QtWidgets/QComboBox>
#include <QtWidgets/QDockWidget>
#include <QtWidgets/QLabel>
#include <QtWidgets/QListView>
#include <QtWidgets/QMenu>
#include <QtWidgets/QSlider>
#include <QtWidgets/QToolButton>
#include <QtWidgets/QWidget>
#include <QtWidgets/QWidgetAction>

#include <windows.h>

namespace {

typedef void (*ValueChangedCallback)(int channelIndex, const wchar_t *modeName,
                                     double opacity);
typedef void (*ResolveChannelsCallback)(int count,
                                        const wchar_t *const *buttonTexts);
typedef void (*ValueRequestCallback)(void);
typedef void (*LayerControlsChangedCallback)(void);

ValueChangedCallback g_valueCallback = nullptr;
ResolveChannelsCallback g_resolveCallback = nullptr;
ValueRequestCallback g_valueRequestCallback = nullptr;
LayerControlsChangedCallback g_layerControlsCallback = nullptr;

struct ChannelInfo {
    QString id;
    QString label;
};

struct BlendModeInfo {
    QString name;
    QString label;
};

QVector<ChannelInfo> g_channels;
QVector<BlendModeInfo> g_blendModes;

QPointer<QWidget> g_propertiesPanel;
QPointer<QWidget> g_host;
QPointer<QWidget> g_panelWidget;
QVector<QPointer<QToolButton>> g_blendButtons;
QVector<QPointer<QToolButton>> g_opacityButtons;
QVector<QPointer<QSlider>> g_opacitySliders;
QTimer *g_timer = nullptr;
QTimer *g_controlsTimer = nullptr;
QObject *g_refreshFilter = nullptr;
bool g_refreshPending = false;
bool g_enabled = true;
bool g_syncing = false;
QString g_lastBlendText;
QString g_lastOpacityText;
QString g_selectedLayerName;

QString normalized(const QString &text) {
    QString out;
    for (const QChar character : text) {
        const ushort code = character.unicode();
        const bool keep = (code >= 'a' && code <= 'z') ||
                          (code >= '0' && code <= '9') ||
                          (code >= 0x3400 && code <= 0x9fff);
        if (keep)
            out.append(character.toLower());
    }
    return out;
}

QWidget *findPropertiesPanel() {
    for (QWidget *widget : QApplication::allWidgets()) {
        if (auto *dock = qobject_cast<QDockWidget *>(widget)) {
            const QString title = dock->windowTitle();
            if (title.contains(QStringLiteral("属性")) ||
                normalized(title).contains(QStringLiteral("properties")))
                return dock;
        }
    }
    return nullptr;
}

QList<QToolButton *> findChannelButtons(QWidget *panel) {
    QList<QToolButton *> result;
    for (QToolButton *button : panel->findChildren<QToolButton *>()) {
        if (!button->isVisible())
            continue;
        if (button->objectName() != QStringLiteral("channelSelector"))
            continue;
        if (button->text().trimmed().isEmpty())
            continue;
        result.append(button);
    }
    std::sort(result.begin(), result.end(),
              [](QToolButton *a, QToolButton *b) {
                  return a->geometry().x() < b->geometry().x();
              });
    return result;
}

QWidget *findLayersPanel() {
    for (QWidget *widget : QApplication::allWidgets()) {
        if (auto *dock = qobject_cast<QDockWidget *>(widget)) {
            const QString title = dock->windowTitle();
            if (title.contains(QStringLiteral("图层")) ||
                normalized(title).contains(QStringLiteral("layers")))
                return dock;
        }
    }
    return nullptr;
}

QWidget *findSelectedLayerRow() {
    QWidget *layers = findLayersPanel();
    if (!layers)
        return nullptr;
    // 1) 通过图层列表当前索引定位行
    for (QListView *view : layers->findChildren<QListView *>()) {
        if (view->objectName() != QStringLiteral("layerListView"))
            continue;
        const QModelIndex index = view->currentIndex();
        if (index.isValid()) {
            if (QWidget *row = view->indexWidget(index))
                return row;
        }
    }
    // 2) 按选中图层名匹配行
    if (!g_selectedLayerName.isEmpty()) {
        for (QLabel *label : layers->findChildren<QLabel *>()) {
            if (!label->isVisible())
                continue;
            if (label->text().trimmed() != g_selectedLayerName)
                continue;
            QWidget *row = label->parentWidget();
            for (int depth = 0; depth < 10 && row; ++depth) {
                if (row->findChild<QToolButton *>(
                        QStringLiteral("blendingMode")))
                    return row;
                row = row->parentWidget();
            }
        }
    }
    return nullptr;
}

void pollLayerControls() {
    if (!g_enabled || !g_layerControlsCallback)
        return;
    QWidget *row = findSelectedLayerRow();
    QString blendText;
    QString opacityText;
    if (row) {
        if (QToolButton *blend = row->findChild<QToolButton *>(
                QStringLiteral("blendingMode")))
            blendText = blend->text().trimmed();
        if (QToolButton *opacity = row->findChild<QToolButton *>(
                QStringLiteral("opacity")))
            opacityText = opacity->text().trimmed();
    }
    if (blendText != g_lastBlendText || opacityText != g_lastOpacityText) {
        g_lastBlendText = blendText;
        g_lastOpacityText = opacityText;
        // 图层面板控件变化：通知 Python 重新同步各通道值
        g_layerControlsCallback();
    }
}

void applyReferenceStyle(QWidget *propertiesPanel, QToolButton *blendButton,
                         QToolButton *opacityButton, QSlider *slider) {
    // 从面板中原生的深色下拉框复制调色板，保证与 Painter 主题一致
    QPalette reference = QApplication::palette();
    if (propertiesPanel) {
        for (QComboBox *nativeCombo : propertiesPanel->findChildren<QComboBox *>()) {
            if (!nativeCombo->isVisible())
                continue;
            if (nativeCombo->objectName().startsWith(QStringLiteral("sp_tools")))
                continue;
            reference = nativeCombo->palette();
            break;
        }
    }
    blendButton->setPalette(reference);
    opacityButton->setPalette(reference);
    slider->setPalette(reference);
}

QWidget *buildPanel(int rowHeight, QWidget *propertiesPanel) {
    auto *panel = new QWidget();
    panel->setObjectName(QStringLiteral("sp_tools_channel_panel"));
    auto *vbox = new QVBoxLayout(panel);
    vbox->setContentsMargins(0, 2, 0, 2);
    vbox->setSpacing(2);
    g_blendButtons.clear();
    g_opacityButtons.clear();
    g_opacitySliders.clear();

    for (int i = 0; i < g_channels.size(); ++i) {
        auto *row = new QHBoxLayout();
        row->setSpacing(4);
        auto *label = new QLabel(g_channels[i].label);
        label->setMinimumWidth(56);
        // 混合模式：与图层面板一致 —— QToolButton('blendingMode') + blendingModeMenu
        auto *blendButton = new QToolButton();
        blendButton->setObjectName(QStringLiteral("blendingMode"));
        blendButton->setPopupMode(QToolButton::InstantPopup);
        blendButton->setFixedHeight(rowHeight > 0 ? rowHeight : 22);
        blendButton->setMinimumWidth(92);
        blendButton->setText(QStringLiteral("正常"));
        blendButton->setProperty("sp_tools_mode_name", QString());
        auto *blendMenu = new QMenu(blendButton);
        blendMenu->setObjectName(QStringLiteral("blendingModeMenu"));
        for (const BlendModeInfo &mode : g_blendModes)
            blendMenu->addAction(mode.label)->setData(mode.name);
        blendButton->setMenu(blendMenu);

        // 不透明度：与图层面板一致 —— QToolButton('opacity') + opacityMenu（含滑块）
        auto *opacityButton = new QToolButton();
        opacityButton->setObjectName(QStringLiteral("opacity"));
        opacityButton->setPopupMode(QToolButton::InstantPopup);
        opacityButton->setFixedHeight(rowHeight > 0 ? rowHeight : 22);
        opacityButton->setMinimumWidth(52);
        opacityButton->setText(QStringLiteral("100"));
        auto *opacityMenu = new QMenu(opacityButton);
        opacityMenu->setObjectName(QStringLiteral("opacityMenu"));
        auto *sliderAction = new QWidgetAction(opacityMenu);
        auto *opacitySlider = new QSlider(Qt::Horizontal);
        opacitySlider->setObjectName(QStringLiteral("slider_"));
        opacitySlider->setRange(0, 100);
        opacitySlider->setFixedWidth(160);
        sliderAction->setDefaultWidget(opacitySlider);
        opacityMenu->addAction(sliderAction);
        opacityButton->setMenu(opacityMenu);
        row->addWidget(label);
        row->addWidget(blendButton, 1);
        row->addWidget(opacityButton);
        vbox->addLayout(row);
        g_blendButtons.append(blendButton);
        g_opacityButtons.append(opacityButton);
        g_opacitySliders.append(opacitySlider);
        applyReferenceStyle(propertiesPanel, blendButton, opacityButton,
                            opacitySlider);

        const int index = i;
        QObject::connect(blendMenu, &QMenu::triggered, panel,
                         [index](QAction *action) {
            QToolButton *blendButton = g_blendButtons.value(index);
            const QString modeName = action->data().toString();
            if (blendButton) {
                blendButton->setText(action->text());
                blendButton->setProperty("sp_tools_mode_name", modeName);
            }
            if (g_syncing || !g_valueCallback)
                return;
            QSlider *slider = g_opacitySliders.value(index);
            g_valueCallback(index, modeName.toStdWString().c_str(),
                            slider ? slider->value() : 0);
        });
        QObject::connect(opacitySlider, &QSlider::valueChanged, panel,
                         [index](int value) {
            QToolButton *button = g_opacityButtons.value(index);
            if (button)
                button->setText(QString::number(value));
            if (g_syncing || !g_valueCallback)
                return;
            QToolButton *blendButton = g_blendButtons.value(index);
            if (!blendButton)
                return;
            const QString modeName =
                blendButton->property("sp_tools_mode_name").toString();
            g_valueCallback(index, modeName.toStdWString().c_str(), value);
        });
    }
    return panel;
}

QString modeLabelForName(const QString &name) {
    for (const BlendModeInfo &mode : g_blendModes)
        if (mode.name == name)
            return mode.label;
    return QString();
}

bool onPanelRefresh();
bool inject();

class PanelRefreshFilter final : public QObject {
public:
    using QObject::QObject;

protected:
    bool eventFilter(QObject *obj, QEvent *event) override {
        if (!g_enabled)
            return false;
        const QEvent::Type type = event->type();
        if (type != QEvent::Show && type != QEvent::Polish &&
            type != QEvent::LayoutRequest && type != QEvent::Resize)
            return false;
        if (!isInsidePropertiesPanel(obj))
            return false;
        if (!g_refreshPending) {
            g_refreshPending = true;
            QTimer::singleShot(0, [] {
                g_refreshPending = false;
                onPanelRefresh();
            });
        }
        return false;
    }

private:
    static bool isInsidePropertiesPanel(QObject *obj) {
        if (!obj || !g_propertiesPanel)
            return false;
        QWidget *targetWindow = g_propertiesPanel->window();
        for (QObject *current = obj; current; current = current->parent()) {
            if (current == g_propertiesPanel)
                return true;
            if (current->isWidgetType()) {
                QWidget *widget = static_cast<QWidget *>(current);
                if (widget->window() != targetWindow)
                    return false;
            }
        }
        return false;
    }
};

bool onPanelRefresh() {
    if (!g_enabled)
        return false;
    // 面板刷新：必要时重新注入（面板可能已被重建）
    inject();
    // 控件就绪则重新拉取图层当前值
    if (g_panelWidget && g_panelWidget->isVisible() && g_valueRequestCallback)
        g_valueRequestCallback();
    return true;
}

bool inject() {
    if (!g_enabled)
        return false;
    QWidget *panel = findPropertiesPanel();
    if (!panel)
        return false;
    const QList<QToolButton *> buttons = findChannelButtons(panel);
    if (buttons.isEmpty())
        return false;
    // 按钮数量与已知通道不一致：回调 Python，让它按按钮文字解析通道列表
    if (buttons.size() != g_channels.size()) {
        if (g_resolveCallback) {
            QVector<QString> texts;
            QVector<const wchar_t *> pointers;
            texts.reserve(buttons.size());
            pointers.reserve(buttons.size());
            for (const QToolButton *button : buttons) {
                texts.append(button->text().trimmed());
                pointers.append(
                    reinterpret_cast<const wchar_t *>(texts.last().utf16()));
            }
            g_resolveCallback(pointers.size(), pointers.constData());
        }
        if (buttons.size() != g_channels.size())
            return false;
    }
    QWidget *container = buttons.first()->parentWidget();
    if (!container)
        return false;
    QWidget *host = container->parentWidget();
    if (!host)
        return false;
    QLayout *layout = host->layout();
    if (!layout)
        return false;

    // 已注入且仍然有效
    if (g_panelWidget && g_host == host && g_panelWidget->isVisible())
        return true;

    // 移除旧的（如果还在）
    if (g_panelWidget) {
        if (QWidget *oldParent = g_panelWidget->parentWidget()) {
            if (QLayout *oldLayout = oldParent->layout())
                oldLayout->removeWidget(g_panelWidget);
        }
        g_panelWidget->deleteLater();
        g_panelWidget = nullptr;
    }

    int rowHeight = 0;
    for (const QToolButton *button : buttons)
        rowHeight = qMax(rowHeight, button->height());

    QWidget *panelWidget = buildPanel(rowHeight, panel);
    const int index = layout->indexOf(container);
    if (auto *box = qobject_cast<QBoxLayout *>(layout)) {
        if (index >= 0)
            box->insertWidget(index + 1, panelWidget);
        else
            box->addWidget(panelWidget);
    } else {
        QList<QLayoutItem *> items;
        while (layout->count() > 0)
            items.append(layout->takeAt(0));
        const int insertAt = index >= 0 ? index + 1 : items.size();
        items.insert(insertAt, new QWidgetItem(panelWidget));
        for (QLayoutItem *item : items)
            layout->addItem(item);
    }
    panelWidget->show();
    g_panelWidget = panelWidget;
    g_host = host;
    g_propertiesPanel = panel;
    // 控件就绪后主动向 Python 请求当前图层各通道的值
    if (g_valueRequestCallback)
        g_valueRequestCallback();
    return true;
}

void onFallbackTimer() {
    if (!g_enabled)
        return;
    // 面板被重建/隐藏后自动重新注入
    inject();
}

bool pinThisDll() {
    HMODULE module = nullptr;
    return GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
            GET_MODULE_HANDLE_EX_FLAG_PIN,
        reinterpret_cast<LPCWSTR>(&pinThisDll), &module) != 0;
}

} // namespace

extern "C" __declspec(dllexport) int __cdecl sp_tools_api_version() {
    return 3;
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_enabled(int enabled) {
    g_enabled = enabled != 0;
    if (g_panelWidget)
        g_panelWidget->setVisible(g_enabled);
    if (g_enabled)
        inject();
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_value_callback(ValueChangedCallback callback) {
    g_valueCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_resolve_callback(ResolveChannelsCallback callback) {
    g_resolveCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_value_request_callback(ValueRequestCallback callback) {
    g_valueRequestCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_layer_controls_callback(LayerControlsChangedCallback callback) {
    g_layerControlsCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_selected_layer_name(const wchar_t *name) {
    g_selectedLayerName = name ? QString::fromWCharArray(name) : QString();
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_check_channels() {
    QWidget *panel = findPropertiesPanel();
    if (!panel)
        return;
    const QList<QToolButton *> buttons = findChannelButtons(panel);
    if (buttons.isEmpty())
        return;
    // 通道集变化时（例如切到别的纹理集的图层）立即重新解析并重建
    if (buttons.size() != g_channels.size())
        inject();
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_blend_modes(
    int count, const wchar_t *const *names, const wchar_t *const *labels) {
    g_blendModes.clear();
    for (int i = 0; i < count; ++i) {
        BlendModeInfo info;
        info.name = names && names[i] ? QString::fromWCharArray(names[i])
                                      : QString();
        info.label = labels && labels[i] ? QString::fromWCharArray(labels[i])
                                         : info.name;
        g_blendModes.append(info);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_channels(
    int count, const wchar_t *const *ids, const wchar_t *const *labels) {
    g_channels.clear();
    for (int i = 0; i < count; ++i) {
        ChannelInfo info;
        info.id = ids && ids[i] ? QString::fromWCharArray(ids[i]) : QString();
        info.label = labels && labels[i] ? QString::fromWCharArray(labels[i])
                                         : info.id;
        g_channels.append(info);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_value(
    int index, const wchar_t *modeName, double opacity) {
    if (index < 0 || index >= g_blendButtons.size())
        return;
    QToolButton *blendButton = g_blendButtons.value(index);
    QToolButton *button = g_opacityButtons.value(index);
    QSlider *slider = g_opacitySliders.value(index);
    if (!blendButton || !button || !slider)
        return;
    const QString mode = modeName ? QString::fromWCharArray(modeName)
                                  : QString();
    const bool valid = !mode.isEmpty() && opacity >= 0.0;
    g_syncing = true;
    const QString label = modeLabelForName(mode);
    if (!label.isEmpty()) {
        blendButton->setText(label);
        blendButton->setProperty("sp_tools_mode_name", mode);
    }
    if (opacity >= 0.0) {
        const int value = qBound(0, qRound(opacity), 100);
        slider->setValue(value);
        button->setText(QString::number(value));
    }
    blendButton->setEnabled(valid);
    button->setEnabled(valid);
    slider->setEnabled(valid);
    g_syncing = false;
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_reinject() {
    if (g_panelWidget) {
        if (QWidget *oldParent = g_panelWidget->parentWidget()) {
            if (QLayout *oldLayout = oldParent->layout())
                oldLayout->removeWidget(g_panelWidget);
        }
        g_panelWidget->deleteLater();
        g_panelWidget = nullptr;
    }
    inject();
}

extern "C" __declspec(dllexport) int __cdecl sp_tools_install(void *appPtr) {
    pinThisDll();
    QApplication *application =
        appPtr ? reinterpret_cast<QApplication *>(appPtr) : nullptr;
    if (!application)
        application = qobject_cast<QApplication *>(QCoreApplication::instance());
    if (!application)
        return 0;
    if (!g_timer) {
        g_timer = new QTimer(application);
        g_timer->setInterval(2000);
        QObject::connect(g_timer, &QTimer::timeout, [] { onFallbackTimer(); });
        g_timer->start();
    }
    if (!g_controlsTimer) {
        g_controlsTimer = new QTimer(application);
        g_controlsTimer->setInterval(400);
        QObject::connect(g_controlsTimer, &QTimer::timeout,
                         [] { pollLayerControls(); });
        g_controlsTimer->start();
    }
    // Painter 退出时先停掉所有定时器并禁用插件，避免在控件销毁过程中
    // 继续访问 UI（否则退出时会崩溃）。
    static bool quitHookConnected = false;
    if (!quitHookConnected) {
        quitHookConnected = true;
        QObject::connect(application, &QCoreApplication::aboutToQuit, [] {
            g_enabled = false;
            if (g_timer)
                g_timer->stop();
            if (g_controlsTimer)
                g_controlsTimer->stop();
            if (g_refreshFilter)
                QCoreApplication::instance()->removeEventFilter(g_refreshFilter);
        });
    }
    if (!g_refreshFilter) {
        g_refreshFilter = new PanelRefreshFilter();
        application->installEventFilter(g_refreshFilter);
    }
    inject();
    return 1;
}
