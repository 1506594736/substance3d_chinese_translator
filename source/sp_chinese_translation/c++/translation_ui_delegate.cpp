#include <QtCore/QCoreApplication>
#include <QtCore/QEvent>
#include <QtCore/QDir>
#include <QtCore/QFile>
#include <QtCore/QFileInfo>
#include <QtCore/QHash>
#include <QtCore/QJsonDocument>
#include <QtCore/QJsonObject>
#include <QtCore/QPointer>
#include <QtCore/QSaveFile>
#include <QtCore/QTimer>
#include <QtCore/QVariant>
#include <QtGui/QHelpEvent>
#include <QtGui/QContextMenuEvent>
#include <QtGui/QMouseEvent>
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
#include <QtGui/QAction>
#else
#include <QtWidgets/QAction>
#endif
#include <QtGui/QColor>
#include <QtGui/QPainter>
#include <QtGui/QPalette>
#include <QtWidgets/QAbstractButton>
#include <QtWidgets/QAbstractItemView>
#include <QtWidgets/QAbstractSlider>
#include <QtWidgets/QAbstractSpinBox>
#include <QtWidgets/QApplication>
#include <QtWidgets/QComboBox>
#include <QtWidgets/QDockWidget>
#include <QtWidgets/QDialog>
#include <QtWidgets/QDialogButtonBox>
#include <QtWidgets/QFormLayout>
#include <QtWidgets/QGroupBox>
#include <QtWidgets/QLabel>
#include <QtWidgets/QLineEdit>
#include <QtWidgets/QListView>
#include <QtWidgets/QMenu>
#include <QtWidgets/QMessageBox>
#include <QtWidgets/QPushButton>
#include <QtWidgets/QStyledItemDelegate>
#include <QtWidgets/QTabBar>
#include <QtWidgets/QToolButton>
#include <QtWidgets/QToolTip>
#include <QtWidgets/QTreeView>
#include <QtWidgets/QVBoxLayout>

#include <windows.h>

namespace {
QHash<QString, QString> g_translations;
QHash<QString, QString> g_originals;
QHash<QString, QHash<QString, QString>> g_controlTranslations;
QHash<QString, QString> g_translationPaths;
QString g_fallbackPath;
QPointer<QWidget> g_originalTooltipOwner;
bool g_enabled = true;
bool g_translateLayersPanel = true;
constexpr auto kSourceProperty = "_sp_translation_source";
constexpr auto kComboSourcesProperty = "_sp_translation_combo_sources";
constexpr auto kTabSourcesProperty = "_sp_translation_tab_sources";
constexpr auto kTranslatingComboProperty = "_sp_translation_combo_busy";

void resizeStringList(QStringList &values, int size) {
    while (values.size() < size)
        values.append(QString());
    while (values.size() > size)
        values.removeLast();
}

QComboBox *owningComboBox(QAbstractItemView *view) {
    if (!view)
        return nullptr;
    for (QObject *current = view; current; current = current->parent()) {
        if (auto *combo = qobject_cast<QComboBox *>(current))
            return combo;
    }
    // Qt places a combo popup inside a private top-level container on some
    // styles, so its QObject parent chain does not necessarily reach the
    // QComboBox. Comparing view pointers is stable across those styles.
    for (QWidget *widget : QApplication::allWidgets()) {
        if (auto *combo = qobject_cast<QComboBox *>(widget)) {
            if (combo->view() == view)
                return combo;
        }
    }
    return nullptr;
}

QString translated(const QString &text, bool removeMnemonic = false) {
    if (!g_enabled)
        return {};
    QString key = text.trimmed();
    if (removeMnemonic)
        key.remove(u'&');
    // Painter's own localization wins. Instance-specific source properties,
    // not this global lookup, handle text previously produced by the plug-in.
    for (const QChar character : key) {
        const uint code = character.unicode();
        if ((code >= 0x3400 && code <= 0x4DBF) ||
            (code >= 0x4E00 && code <= 0x9FFF))
            return {};
    }
    const auto found = g_translations.constFind(key);
    return found == g_translations.cend() ? QString() : found.value();
}

bool isInsideLayersPanel(QWidget *widget) {
    if (!widget)
        return false;
    for (QObject *parent = widget; parent; parent = parent->parent()) {
        const QString className = QString::fromLatin1(parent->metaObject()->className());
        const QString objectName = parent->objectName();
        if (className.contains("LayerStack") || className.contains("LayerTree") ||
            objectName.contains("DockLayers"))
            return true;
        if (auto *dock = qobject_cast<QDockWidget *>(parent)) {
            const QString title = dock->windowTitle().trimmed();
            if (title == QStringLiteral("Layers") || title == QStringLiteral("图层"))
                return true;
        }
    }
    return false;
}

QString sourceForObject(QObject *object, const QString &displayedText) {
    QString displayed = displayedText.trimmed();
    displayed.remove(u'&');
    if (!object)
        return displayed;
    const QString stored = object->property(kSourceProperty).toString();
    if (stored.isEmpty())
        return displayed;
    if (displayed == stored || g_translations.value(stored) == displayed ||
        g_originals.value(displayed) == stored)
        return stored;
    // Painter reused the object for a different value; ignore stale metadata.
    return displayed;
}

bool shouldExcludeLayersPanel(QWidget *widget) {
    return !g_translateLayersPanel && isInsideLayersPanel(widget);
}

QString controlTranslation(const QString &controlType, const QString &source) {
    return g_controlTranslations.value(controlType).value(source);
}

QString comboSourceAt(QComboBox *combo, int index) {
    if (!combo || index < 0 || index >= combo->count())
        return {};
    const QStringList sources =
        combo->property(kComboSourcesProperty).toStringList();
    const QString displayed = combo->itemText(index).trimmed();
    if (index < sources.size() && !sources.at(index).isEmpty()) {
        const QString stored = sources.at(index);
        if (displayed == stored || g_translations.value(stored) == displayed ||
            g_originals.value(displayed) == stored)
            return stored;
    }
    const auto original = g_originals.constFind(displayed);
    return original == g_originals.cend() ? displayed : original.value();
}

bool isLayerBlendModeCombo(QComboBox *combo) {
    if (!combo || !isInsideLayersPanel(combo))
        return false;
    for (int i = 0; i < combo->count(); ++i) {
        const QString source = comboSourceAt(combo, i);
        if (source == QStringLiteral("Passthrough") ||
            source == QStringLiteral("Normal map combine"))
            return true;
    }
    return false;
}

bool isLayerBlendModeButton(QToolButton *button) {
    return button && button->objectName() == QStringLiteral("blendingMode") &&
           isInsideLayersPanel(button);
}

bool isLayerChannelSelector(QComboBox *combo) {
    return combo && combo->objectName() == QStringLiteral("channelSelector") &&
           isInsideLayersPanel(combo);
}

void lockLayerChannelPopupWidth(QComboBox *combo) {
    if (!isLayerChannelSelector(combo) || !combo->view())
        return;
    const int width = combo->width();
    combo->view()->setMinimumWidth(width);
    combo->view()->setMaximumWidth(width);
    QWidget *popup = combo->view()->window();
    if (popup && popup != combo->window() && popup != combo->view()) {
        popup->setMinimumWidth(width);
        popup->setMaximumWidth(width);
    }
}

QString actionSource(QAction *action) {
    if (!action)
        return {};
    const QString displayed = action->text().trimmed();
    const QString instanceSource = sourceForObject(action, displayed);
    if (instanceSource != displayed)
        return instanceSource;
    const auto original = g_originals.constFind(displayed);
    return original == g_originals.cend() ? displayed : original.value();
}

bool isLayerBlendModeMenu(QMenu *menu) {
    if (!menu)
        return false;
    if (auto *button = qobject_cast<QToolButton *>(menu->parentWidget())) {
        if (isLayerBlendModeButton(button))
            return true;
    }
    for (QAction *action : menu->actions()) {
        const QString source = actionSource(action);
        if (source == QStringLiteral("Passthrough") ||
            source == QStringLiteral("Normal map combine"))
            return true;
    }
    return false;
}

QString menuTranslation(QMenu *menu, const QString &source) {
    return isLayerBlendModeMenu(menu)
        ? controlTranslation(QStringLiteral("layer_blend_mode"), source)
        : g_translations.value(source);
}

class TranslationItemDelegate final : public QStyledItemDelegate {
public:
    explicit TranslationItemDelegate(QAbstractItemView *view,
                                     bool compactGrid = false,
                                     bool layersPanel = false)
        : QStyledItemDelegate(view), compactGrid_(compactGrid),
          layersPanel_(layersPanel) {}

    QString displayText(const QVariant &value, const QLocale &locale) const override {
        if (g_enabled && (!layersPanel_ || g_translateLayersPanel) &&
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
            value.metaType().id() == QMetaType::QString) {
#else
            value.userType() == QMetaType::QString) {
#endif
            const QString result = translated(value.toString());
            if (!result.isNull())
                return result;
        }
        return QStyledItemDelegate::displayText(value, locale);
    }

    void initStyleOption(QStyleOptionViewItem *option,
                         const QModelIndex &index) const override {
        QStyledItemDelegate::initStyleOption(option, index);
        if (!compactGrid_)
            return;
        option->features |= QStyleOptionViewItem::WrapText;
        option->textElideMode = Qt::ElideRight;
        QFont font = option->font;
        const qreal currentSize = font.pointSizeF();
        if (font.pixelSize() > 0)
            font.setPixelSize(qMax(9, font.pixelSize() - 2));
        else if (currentSize > 0.0)
            font.setPointSizeF(qMax<qreal>(7.0, currentSize - 2.0));
        option->font = font;
    }

    QSize sizeHint(const QStyleOptionViewItem &option,
                   const QModelIndex &index) const override {
        QSize size = QStyledItemDelegate::sizeHint(option, index);
        if (compactGrid_) {
            QStyleOptionViewItem adjusted(option);
            initStyleOption(&adjusted, index);
            size.setHeight(size.height() + QFontMetrics(adjusted.font).lineSpacing() + 6);
        }
        return size;
    }

    void paint(QPainter *painter, const QStyleOptionViewItem &option,
               const QModelIndex &index) const override {
        if (!compactGrid_) {
            QStyledItemDelegate::paint(painter, option, index);
            return;
        }

        QStyleOptionViewItem adjusted(option);
        initStyleOption(&adjusted, index);
        const QString text = adjusted.text;

        // Let the native style draw only selection/background/focus. Painter's
        // style ignores transparent text colors, so both display and decoration
        // are removed here; the icon and text are drawn explicitly below.
        QStyleOptionViewItem nativePart(adjusted);
        nativePart.text.clear();
        nativePart.icon = QIcon();
        nativePart.features &= ~QStyleOptionViewItem::HasDisplay;
        nativePart.features &= ~QStyleOptionViewItem::HasDecoration;
        const QWidget *widget = adjusted.widget;
        QStyle *style = widget ? widget->style() : QApplication::style();
        style->drawControl(QStyle::CE_ItemViewItem, &nativePart, painter, widget);

        painter->save();
        const QSize iconSize = adjusted.decorationSize.isValid()
                                   ? adjusted.decorationSize
                                   : QSize(48, 48);
        QRect iconRect(QPoint(0, 0), iconSize);
        iconRect.moveCenter(QPoint(adjusted.rect.center().x(),
                                   adjusted.rect.top() + 4 + iconSize.height() / 2));
        const QIcon::Mode iconMode = (adjusted.state & QStyle::State_Enabled)
                                         ? QIcon::Normal
                                         : QIcon::Disabled;
        const QIcon::State iconState = (adjusted.state & QStyle::State_Open)
                                           ? QIcon::On
                                           : QIcon::Off;
        adjusted.icon.paint(painter, iconRect, Qt::AlignCenter, iconMode, iconState);

        painter->setFont(adjusted.font);
        const bool selected = adjusted.state & QStyle::State_Selected;
        painter->setPen(adjusted.palette.color(
            selected ? QPalette::HighlightedText : QPalette::Text));
        const QFontMetrics metrics(adjusted.font);
        const int twoLines = metrics.lineSpacing() * 2;
        QRect textRect = adjusted.rect.adjusted(2, 0, -2, -2);
        textRect.setTop(iconRect.bottom() + 3);
        textRect.setHeight(twoLines + 2);
        painter->setClipRect(textRect);
        painter->drawText(textRect, Qt::AlignHCenter | Qt::AlignTop |
                                        Qt::TextWordWrap,
                          text);
        painter->restore();
    }

private:
    bool compactGrid_ = false;
    bool layersPanel_ = false;
};

int installAssetDelegate(QAbstractItemView *view, bool compactGrid = false,
                         bool layersPanel = false) {
    if (!view)
        return 0;
    if (dynamic_cast<TranslationItemDelegate *>(view->itemDelegate())) {
        view->viewport()->update();
        return 2;
    }
    if (compactGrid) {
        if (auto *listView = qobject_cast<QListView *>(view)) {
            listView->setWordWrap(true);
            const QSize grid = listView->gridSize();
            const int extraLine = QFontMetrics(listView->font()).lineSpacing();
            if (grid.isValid())
                listView->setGridSize(QSize(grid.width(), grid.height() + extraLine + 6));
        }
        view->setTextElideMode(Qt::ElideRight);
    }
    view->setItemDelegate(
        new TranslationItemDelegate(view, compactGrid, layersPanel));
    view->viewport()->update();
    return 1;
}

bool isResourcePickerView(QAbstractItemView *view) {
    if (!view)
        return false;
    for (QObject *parent = view->parent(); parent; parent = parent->parent()) {
        const QString className = QString::fromLatin1(parent->metaObject()->className());
        if (className == QStringLiteral("Alg::ResourcePickerWidget"))
            return true;
        if (qobject_cast<QMenu *>(parent))
            break;
    }
    return false;
}

bool isResourceFolderTree(QAbstractItemView *view) {
    auto *tree = qobject_cast<QTreeView *>(view);
    if (!tree)
        return false;
    const QString name = tree->objectName();
    if (name != QStringLiteral("tree_view") &&
        name != QStringLiteral("filtered_tree_view"))
        return false;

    bool sawPathPanel = false;
    bool sawResourcesView = false;
    int depth = 0;
    for (QObject *parent = tree->parent(); parent && depth < 12;
         parent = parent->parent(), ++depth) {
        if (parent->objectName() == QStringLiteral("path_filter_panel"))
            sawPathPanel = true;
        if (QString::fromLatin1(parent->metaObject()->className()) ==
            QStringLiteral("Alg::NewResourcesView"))
            sawResourcesView = true;
    }
    return sawPathPanel && sawResourcesView;
}

void translateMenu(QMenu *menu) {
    if (!menu || !g_enabled)
        return;
    const bool layerBlendMode = isLayerBlendModeMenu(menu);
    for (QAction *action : menu->actions()) {
        const QString stored = action->property(kSourceProperty).toString();
        const QString source = layerBlendMode && !stored.isEmpty()
            ? stored : actionSource(action);
        const QString result = layerBlendMode
            ? controlTranslation(QStringLiteral("layer_blend_mode"), source)
            : translated(source, true);
        if (!result.isNull() && action->text() != result) {
            action->setProperty(kSourceProperty, source);
            action->setText(result);
        }
    }
}

void translateWidget(QWidget *widget) {
    if (!widget || !g_enabled)
        return;

    // QToolTip is implemented as a temporary QLabel (QTipLabel). Never feed
    // tooltip contents back through the UI translator: these strings are the
    // deliberately preserved English originals.
    if (widget->windowType() == Qt::ToolTip ||
        QString::fromLatin1(widget->metaObject()->className()) == QStringLiteral("QTipLabel") ||
        (widget->window() && widget->window()->windowType() == Qt::ToolTip))
        return;

    // The application-wide event filter sees every Painter widget. Reject
    // types that this plugin never translates before walking their parent
    // hierarchy; this removes most work from frequent paint/layout events.
    const bool supportedType =
        qobject_cast<QAbstractItemView *>(widget) ||
        qobject_cast<QMenu *>(widget) ||
        qobject_cast<QAbstractButton *>(widget) ||
        qobject_cast<QLabel *>(widget) ||
        qobject_cast<QGroupBox *>(widget) ||
        qobject_cast<QComboBox *>(widget) ||
        qobject_cast<QTabBar *>(widget) ||
        qobject_cast<QDockWidget *>(widget) ||
        qobject_cast<QLineEdit *>(widget);
    if (!supportedType || shouldExcludeLayersPanel(widget))
        return;

    const QString className = QString::fromLatin1(widget->metaObject()->className());
    if (auto *itemView = qobject_cast<QAbstractItemView *>(widget)) {
        if (QComboBox *combo = owningComboBox(itemView);
            isLayerChannelSelector(combo)) {
            lockLayerChannelPopupWidth(combo);
            return;
        }
        if (g_translateLayersPanel && isInsideLayersPanel(itemView)) {
            installAssetDelegate(itemView, false, true);
            return;
        }
        const bool mainResourceView =
            className == QStringLiteral("Alg::ResourceListView") &&
            widget->objectName() == QStringLiteral("resources");
        const bool pickerView = isResourcePickerView(itemView);
        const bool folderTree = isResourceFolderTree(itemView);
        if (mainResourceView || pickerView || folderTree) {
            installAssetDelegate(itemView, pickerView);
            return;
        }
    }

    if (auto *menu = qobject_cast<QMenu *>(widget)) {
        translateMenu(menu);
        return;
    }
    if (auto *button = qobject_cast<QAbstractButton *>(widget)) {
        if (auto *toolButton = qobject_cast<QToolButton *>(button);
            isLayerBlendModeButton(toolButton)) {
            // Painter deliberately uses compact native labels (Pthr, NMid,
            // etc.) in this fixed-width button. Translate only its popup menu.
            return;
        }
        const QString source = sourceForObject(button, button->text());
        const QString result = translated(source, true);
        if (!result.isNull() && button->text() != result) {
            button->setProperty(kSourceProperty, source);
            button->setText(result);
        }
        return;
    }
    if (auto *label = qobject_cast<QLabel *>(widget)) {
        const QString source = sourceForObject(label, label->text());
        const QString result = translated(source, true);
        if (!result.isNull() && label->text() != result) {
            label->setProperty(kSourceProperty, source);
            label->setText(result);
        }
        return;
    }
    if (auto *group = qobject_cast<QGroupBox *>(widget)) {
        const QString source = sourceForObject(group, group->title());
        const QString result = translated(source);
        if (!result.isNull() && group->title() != result) {
            group->setProperty(kSourceProperty, source);
            group->setTitle(result);
        }
        return;
    }
    if (auto *combo = qobject_cast<QComboBox *>(widget)) {
        if (combo->property(kTranslatingComboProperty).toBool())
            return;
        combo->setProperty(kTranslatingComboProperty, true);
        QStringList sources = combo->property(kComboSourcesProperty).toStringList();
        resizeStringList(sources, combo->count());
        const bool layerBlendMode = isLayerBlendModeCombo(combo);
        for (int i = 0; i < combo->count(); ++i) {
            const QString source = comboSourceAt(combo, i);
            const QString result = layerBlendMode
                ? controlTranslation(QStringLiteral("layer_blend_mode"), source)
                : translated(source);
            if (!result.isNull() && combo->itemText(i) != result) {
                sources[i] = source;
                combo->setItemText(i, result);
            }
        }
        combo->setProperty(kComboSourcesProperty, sources);
        if (isLayerChannelSelector(combo))
            lockLayerChannelPopupWidth(combo);
        combo->setProperty(kTranslatingComboProperty, false);
        return;
    }
    if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        QStringList sources = tabs->property(kTabSourcesProperty).toStringList();
        resizeStringList(sources, tabs->count());
        for (int i = 0; i < tabs->count(); ++i) {
            const QString displayed = tabs->tabText(i).trimmed();
            QString source = displayed;
            if (i < sources.size() && !sources.at(i).isEmpty()) {
                const QString stored = sources.at(i);
                if (displayed == stored || g_translations.value(stored) == displayed ||
                    g_originals.value(displayed) == stored)
                    source = stored;
            }
            const QString result = translated(source);
            if (!result.isNull() && tabs->tabText(i) != result) {
                sources[i] = source;
                tabs->setTabText(i, result);
            }
        }
        tabs->setProperty(kTabSourcesProperty, sources);
        return;
    }
    if (auto *dock = qobject_cast<QDockWidget *>(widget)) {
        const QString source = sourceForObject(dock, dock->windowTitle());
        const QString result = translated(source);
        if (!result.isNull() && dock->windowTitle() != result) {
            dock->setProperty(kSourceProperty, source);
            dock->setWindowTitle(result);
        }
        return;
    }
    if (auto *lineEdit = qobject_cast<QLineEdit *>(widget)) {
        const QString source = sourceForObject(lineEdit, lineEdit->placeholderText());
        const QString result = translated(source);
        if (!result.isNull() && lineEdit->placeholderText() != result) {
            lineEdit->setProperty(kSourceProperty, source);
            lineEdit->setPlaceholderText(result);
        }
    }
}

QString originalTextAt(QWidget *widget, const QPoint &position) {
    if (!widget || !g_enabled)
        return {};

    // QMenu paints all entries itself, so there is no child label from which
    // the generic tooltip path can recover the source. Only actions actually
    // translated by this plug-in carry this marker; Painter's native entries
    // and their own help text remain untouched.
    if (auto *menu = qobject_cast<QMenu *>(widget)) {
        QAction *action = menu->actionAt(position);
        if (!action || action->isSeparator())
            return {};
        const QString source = action->property(kSourceProperty).toString().trimmed();
        if (source.isEmpty())
            return {};
        QString displayed = action->text().trimmed();
        displayed.remove(u'&');
        return menuTranslation(menu, source) == displayed ? source : QString();
    }

    // The open part of a QComboBox is an independent item-view viewport.
    // Resolve the hovered row through its owning combo instead of treating it
    // as an asset view (whose thumbnail tooltip must remain untouched).
    if (auto *view = qobject_cast<QAbstractItemView *>(widget->parentWidget())) {
        if (widget == view->viewport()) {
            if (QComboBox *combo = owningComboBox(view)) {
                const QModelIndex index = view->indexAt(position);
                if (!index.isValid())
                    return {};
                const int row = index.row();
                const QString displayed = index.data(Qt::DisplayRole).toString().trimmed();
                const QStringList sources =
                    combo->property(kComboSourcesProperty).toStringList();
                if (row >= 0 && row < sources.size()) {
                    const QString source = sources.at(row);
                    const QString expected = isLayerBlendModeCombo(combo)
                        ? controlTranslation(QStringLiteral("layer_blend_mode"), source)
                        : g_translations.value(source);
                    if (!source.isEmpty() && expected == displayed)
                        return source;
                }
                const auto original = g_originals.constFind(displayed);
                return original == g_originals.cend() ? QString() : original.value();
            }
        }
    }

    // Preserve existing tooltips on non-label controls. Parameter labels are
    // handled specially: replace Painter's long description with the concise
    // English source name from our reverse dictionary.
    if (!widget->toolTip().isEmpty() && !qobject_cast<QLabel *>(widget))
        return {};

    // Original-text hints are useful for named UI concepts, not for values or
    // direct-manipulation controls. Painter also has custom subclasses whose
    // names identify the same editor categories.
    const QString widgetClass = QString::fromLatin1(widget->metaObject()->className());
    if (qobject_cast<QAbstractSlider *>(widget) ||
        qobject_cast<QAbstractSpinBox *>(widget) ||
        qobject_cast<QLineEdit *>(widget) ||
        widgetClass.contains(QStringLiteral("Slider"), Qt::CaseInsensitive) ||
        widgetClass.contains(QStringLiteral("SpinBox"), Qt::CaseInsensitive) ||
        widgetClass.contains(QStringLiteral("Numeric"), Qt::CaseInsensitive) ||
        widgetClass.contains(QStringLiteral("Number"), Qt::CaseInsensitive) ||
        widgetClass.contains(QStringLiteral("Color"), Qt::CaseInsensitive))
        return {};

    // Painter builds a slider from several plain QWidget/QLabel children.
    // Inspecting only the leaf type therefore misses its title, value field
    // and track. Reject the entire value-editor family through its parent chain.
    if (!qobject_cast<QLabel *>(widget)) {
        for (QObject *current = widget; current; current = current->parent()) {
            const QString className = QString::fromLatin1(current->metaObject()->className());
            const QString objectName = current->objectName();
            if (className == QStringLiteral("Alg::Slider") ||
                className == QStringLiteral("Alg::SliderHeader") ||
                className == QStringLiteral("Alg::InternalSlider") ||
                className == QStringLiteral("Alg::CustomLineEdit") ||
                className == QStringLiteral("Alg::ColorButton") ||
                objectName == QStringLiteral("colorZone") ||
                objectName == QStringLiteral("value"))
                return {};
            if (className == QStringLiteral("Alg::AbstractDataView"))
                break;
        }
    }

    // Painter owns asset-view tooltips and uses them for thumbnail/large
    // previews, so those events must remain untouched. The resource folder
    // tree has no asset preview; keep the useful English-original tooltip only
    // there. Translation itself still happens in the delegate paint path.
    if (auto *view = qobject_cast<QAbstractItemView *>(widget->parentWidget())) {
        if (widget == view->viewport()) {
            if (isResourceFolderTree(view)) {
                const QModelIndex index = view->indexAt(position);
                if (index.isValid()) {
                    const QString source =
                        index.data(Qt::DisplayRole).toString().trimmed();
                    if (g_translations.contains(source))
                        return source;
                }
            }
            if (g_translateLayersPanel && isInsideLayersPanel(view)) {
                const QModelIndex index = view->indexAt(position);
                if (index.isValid()) {
                    const QString source =
                        index.data(Qt::DisplayRole).toString().trimmed();
                    if (g_translations.contains(source))
                        return source;
                }
            }
            return {};
        }
    }

    QString displayed;
    if (auto *button = qobject_cast<QAbstractButton *>(widget))
        displayed = button->text();
    else if (auto *label = qobject_cast<QLabel *>(widget))
        displayed = label->text();
    else if (auto *group = qobject_cast<QGroupBox *>(widget))
        displayed = group->title();
    else if (auto *combo = qobject_cast<QComboBox *>(widget)) {
        displayed = combo->currentText();
        const QStringList sources =
            combo->property(kComboSourcesProperty).toStringList();
        const int index = combo->currentIndex();
        if (index >= 0 && index < sources.size()) {
            const QString source = sources.at(index);
            if (!source.isEmpty() && g_translations.value(source) == displayed)
                return source;
        }
    }
    else if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        const int tab = tabs->tabAt(position);
        if (tab >= 0) {
            displayed = tabs->tabText(tab);
            const QStringList sources =
                tabs->property(kTabSourcesProperty).toStringList();
            if (tab < sources.size()) {
                const QString source = sources.at(tab);
                if (!source.isEmpty() && g_translations.value(source) == displayed)
                    return source;
            }
        }
    }
    else if (auto *dock = qobject_cast<QDockWidget *>(widget))
        displayed = dock->windowTitle();

    displayed.remove(u'&');
    displayed = displayed.trimmed();
    const auto found = g_originals.constFind(displayed);
    return found == g_originals.cend() ? QString() : found.value();
}

bool shouldSuppressTooltip(QWidget *widget) {
    if (!widget)
        return false;

    // A parameter title is meaningful translated text even when it is a child
    // of Alg::Slider or owns Painter's long descriptive tooltip. The tooltip
    // event will be replaced by the concise English source label.
    if (qobject_cast<QLabel *>(widget))
        return false;

    if (qobject_cast<QAbstractSlider *>(widget) ||
        qobject_cast<QAbstractSpinBox *>(widget) ||
        qobject_cast<QLineEdit *>(widget))
        return true;

    for (QObject *current = widget; current; current = current->parent()) {
        const QString className = QString::fromLatin1(current->metaObject()->className());
        const QString objectName = current->objectName();
        if (className == QStringLiteral("Alg::Slider") ||
            className == QStringLiteral("Alg::SliderHeader") ||
            className == QStringLiteral("Alg::InternalSlider") ||
            className == QStringLiteral("Alg::CustomLineEdit") ||
            className == QStringLiteral("Alg::ColorButton") ||
            objectName == QStringLiteral("colorZone") ||
            objectName == QStringLiteral("value"))
            return true;
        if (className == QStringLiteral("Alg::AbstractDataView"))
            break;
    }
    return false;
}

QString contextSourceAt(QWidget *widget, const QPoint &position) {
    if (!widget || shouldExcludeLayersPanel(widget))
        return {};

    if (auto *view = qobject_cast<QAbstractItemView *>(widget->parentWidget())) {
        if (widget == view->viewport()) {
            const QModelIndex index = view->indexAt(position);
            if (index.isValid()) {
                const QString displayed =
                    index.data(Qt::DisplayRole).toString().trimmed();
                if (QComboBox *combo = owningComboBox(view)) {
                    const QStringList sources =
                        combo->property(kComboSourcesProperty).toStringList();
                    if (index.row() >= 0 && index.row() < sources.size() &&
                        !sources.at(index.row()).isEmpty())
                        return sources.at(index.row());
                    const auto original = g_originals.constFind(displayed);
                    return original == g_originals.cend()
                        ? QString() : original.value();
                }
                return displayed;
            }
            return {};
        }
    }

    QString displayed;
    if (auto *menu = qobject_cast<QMenu *>(widget)) {
        QAction *action = menu->actionAt(position);
        if (!action || action->isSeparator())
            return {};
        displayed = action->text();
        const QString storedSource = action->property(kSourceProperty).toString();
        if (!storedSource.isEmpty() &&
            menuTranslation(menu, storedSource) == displayed)
            return storedSource;
        // Chinese menu text without our source marker belongs to Painter (or
        // another plug-in), so it must not be offered as one of our entries.
        for (const QChar character : displayed) {
            const uint code = character.unicode();
            if ((code >= 0x3400 && code <= 0x4DBF) ||
                (code >= 0x4E00 && code <= 0x9FFF))
                return {};
        }
    } else if (auto *button = qobject_cast<QAbstractButton *>(widget))
        displayed = button->text();
    else if (auto *label = qobject_cast<QLabel *>(widget))
        displayed = label->text();
    else if (auto *group = qobject_cast<QGroupBox *>(widget))
        displayed = group->title();
    else if (auto *combo = qobject_cast<QComboBox *>(widget)) {
        displayed = combo->currentText();
        const QStringList sources =
            combo->property(kComboSourcesProperty).toStringList();
        const int index = combo->currentIndex();
        if (index >= 0 && index < sources.size() && !sources.at(index).isEmpty())
            return sources.at(index);
    }
    else if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        const int tab = tabs->tabAt(position);
        if (tab >= 0) {
            displayed = tabs->tabText(tab);
            const QStringList sources =
                tabs->property(kTabSourcesProperty).toStringList();
            if (tab < sources.size() && !sources.at(tab).isEmpty())
                return sources.at(tab);
        }
    }
    else if (auto *dock = qobject_cast<QDockWidget *>(widget))
        displayed = dock->windowTitle();

    displayed.remove(u'&');
    displayed = displayed.trimmed();
    const QString storedSource = widget->property(kSourceProperty).toString();
    if (!storedSource.isEmpty() && g_translations.value(storedSource) == displayed)
        return storedSource;
    const auto original = g_originals.constFind(displayed);
    if (original != g_originals.cend())
        return original.value();
    for (const QChar character : displayed) {
        const uint code = character.unicode();
        if ((code >= 0x3400 && code <= 0x4DBF) ||
            (code >= 0x4E00 && code <= 0x9FFF))
            return {};
    }
    return displayed;
}

QString controlTypeAt(QWidget *widget) {
    if (!widget)
        return QStringLiteral("未知控件");
    const QString className =
        QString::fromLatin1(widget->metaObject()->className());

    if (qobject_cast<QMenu *>(widget))
        return QStringLiteral("菜单项（%1 / QAction）").arg(className);
    if (auto *view = qobject_cast<QAbstractItemView *>(widget->parentWidget())) {
        if (widget == view->viewport()) {
            const QString viewClass =
                QString::fromLatin1(view->metaObject()->className());
            if (owningComboBox(view))
                return QStringLiteral("下拉菜单选项（%1）").arg(viewClass);
            if (isInsideLayersPanel(view))
                return QStringLiteral("图层名称（%1）").arg(viewClass);
            if (isResourceFolderTree(view))
                return QStringLiteral("资产目录项（%1）").arg(viewClass);
            return QStringLiteral("列表项目（%1）").arg(viewClass);
        }
    }
    if (qobject_cast<QAbstractButton *>(widget))
        return QStringLiteral("按钮（%1）").arg(className);
    if (qobject_cast<QLabel *>(widget))
        return QStringLiteral("文本标签（%1）").arg(className);
    if (qobject_cast<QGroupBox *>(widget))
        return QStringLiteral("分组标题（%1）").arg(className);
    if (qobject_cast<QComboBox *>(widget))
        return QStringLiteral("下拉框（%1）").arg(className);
    if (qobject_cast<QTabBar *>(widget))
        return QStringLiteral("选项卡（%1）").arg(className);
    if (qobject_cast<QDockWidget *>(widget))
        return QStringLiteral("面板标题（%1）").arg(className);
    return QStringLiteral("界面控件（%1）").arg(className);
}

bool saveTranslation(const QString &source, const QString &target,
                     const QString &controlType, QString *error) {
    const QString translationPath = g_translationPaths.value(source, g_fallbackPath);
    if (translationPath.isEmpty()) {
        if (error)
            *error = QStringLiteral("未配置可写入的翻译文件。");
        return false;
    }

    QJsonObject root;
    QFile existing(translationPath);
    const bool existed = existing.exists();
    if (existed && existing.open(QIODevice::ReadOnly)) {
        QJsonParseError parseError;
        const QJsonDocument document =
            QJsonDocument::fromJson(existing.readAll(), &parseError);
        if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
            if (error)
                *error = QStringLiteral("Translation JSON is invalid: %1")
                             .arg(translationPath);
            existing.close();
            return false;
        }
        root = document.object();
        existing.close();
    } else if (existed) {
        if (error)
            *error = existing.errorString();
        return false;
    }

    if (!existed && translationPath == g_fallbackPath) {
        root.insert(QStringLiteral("$schema"), QStringLiteral("sp-translation-v1"));
        root.insert(QStringLiteral("id"), QStringLiteral("user-added-translations"));
        root.insert(QStringLiteral("language"), QStringLiteral("zh-CN"));
        root.insert(QStringLiteral("description"),
                    QStringLiteral("Translations added from Substance 3D Painter"));
    } else if (root.value(QStringLiteral("$schema")).toString() !=
               QStringLiteral("sp-translation-v1")) {
        if (error)
            *error = QStringLiteral("原始翻译文件格式无效：%1").arg(translationPath);
        return false;
    }
    if (controlType.isEmpty()) {
        QJsonObject translations =
            root.value(QStringLiteral("translations")).toObject();
        translations.insert(source, target);
        root.insert(QStringLiteral("translations"), translations);
    } else {
        QJsonObject controlTypes =
            root.value(QStringLiteral("control_types")).toObject();
        QJsonObject section = controlTypes.value(controlType).toObject();
        QJsonObject translations =
            section.value(QStringLiteral("translations")).toObject();
        translations.insert(source, target);
        section.insert(QStringLiteral("translations"), translations);
        controlTypes.insert(controlType, section);
        root.insert(QStringLiteral("control_types"), controlTypes);
    }

    const QFileInfo info(translationPath);
    if (!QDir().mkpath(info.absolutePath())) {
        if (error)
            *error = QStringLiteral("无法访问翻译文件目录：%1").arg(info.absolutePath());
        return false;
    }
    QSaveFile output(translationPath);
    if (!output.open(QIODevice::WriteOnly)) {
        if (error)
            *error = output.errorString();
        return false;
    }
    output.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    if (!output.commit()) {
        if (error)
            *error = output.errorString();
        return false;
    }
    g_translationPaths.insert(source, translationPath);
    return true;
}

void refreshTranslatedViews() {
    for (QWidget *widget : QApplication::allWidgets()) {
        if (!widget)
            continue;
        if (auto *view = qobject_cast<QAbstractItemView *>(widget))
            view->viewport()->update();
        if (widget->isVisible())
            translateWidget(widget);
    }
}

void restoreTranslatedWidget(QWidget *widget) {
    if (!widget)
        return;
    if (auto *view = qobject_cast<QAbstractItemView *>(widget)) {
        view->viewport()->update();
        return;
    }
    if (auto *menu = qobject_cast<QMenu *>(widget)) {
        for (QAction *action : menu->actions()) {
            const QString source = action->property(kSourceProperty).toString();
            if (!source.isEmpty()) {
                action->setText(source);
                action->setProperty(kSourceProperty, QVariant());
            }
        }
        return;
    }
    if (auto *combo = qobject_cast<QComboBox *>(widget)) {
        const QStringList sources =
            combo->property(kComboSourcesProperty).toStringList();
        for (int i = 0; i < combo->count() && i < sources.size(); ++i) {
            if (!sources.at(i).isEmpty())
                combo->setItemText(i, sources.at(i));
        }
        combo->setProperty(kComboSourcesProperty, QVariant());
        return;
    }
    if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        const QStringList sources =
            tabs->property(kTabSourcesProperty).toStringList();
        for (int i = 0; i < tabs->count() && i < sources.size(); ++i) {
            if (!sources.at(i).isEmpty())
                tabs->setTabText(i, sources.at(i));
        }
        tabs->setProperty(kTabSourcesProperty, QVariant());
        return;
    }

    const QString source = widget->property(kSourceProperty).toString();
    if (source.isEmpty())
        return;
    if (auto *button = qobject_cast<QAbstractButton *>(widget))
        button->setText(source);
    else if (auto *label = qobject_cast<QLabel *>(widget))
        label->setText(source);
    else if (auto *group = qobject_cast<QGroupBox *>(widget))
        group->setTitle(source);
    else if (auto *dock = qobject_cast<QDockWidget *>(widget))
        dock->setWindowTitle(source);
    else if (auto *lineEdit = qobject_cast<QLineEdit *>(widget))
        lineEdit->setPlaceholderText(source);
    widget->setProperty(kSourceProperty, QVariant());
}

void setTranslateLayersPanel(bool enabled) {
    if (g_translateLayersPanel == enabled)
        return;
    g_translateLayersPanel = enabled;
    if (enabled) {
        refreshTranslatedViews();
        return;
    }
    for (QWidget *widget : QApplication::allWidgets()) {
        if (isInsideLayersPanel(widget))
            restoreTranslatedWidget(widget);
    }
}

void editTranslation(const QString &source, const QString &controlType,
                     QWidget *parent) {
    if (source.isEmpty())
        return;
    QString scopedControlType;
    QString current = g_translations.value(source);
    if (current.isNull()) {
        for (auto it = g_controlTranslations.cbegin();
             it != g_controlTranslations.cend(); ++it) {
            const auto found = it.value().constFind(source);
            if (found != it.value().cend()) {
                scopedControlType = it.key();
                current = found.value();
                break;
            }
        }
    }
    if (current.isNull())
        current = source;

    QWidget *dialogParent = QApplication::activeWindow();
    if (!dialogParent)
        dialogParent = parent;
    if (qobject_cast<QMenu *>(dialogParent))
        dialogParent = nullptr;
    QDialog dialog(dialogParent);
    dialog.setWindowTitle(QStringLiteral("更改翻译"));
    dialog.setMinimumWidth(460);
    QPalette dialogPalette = QApplication::palette();
    const QColor windowColor = dialogPalette.color(QPalette::Window);
    const QColor editorColor = windowColor.lightness() < 128
        ? windowColor.lighter(118) : windowColor.darker(104);
    dialogPalette.setColor(QPalette::Base, editorColor);
    dialogPalette.setColor(QPalette::AlternateBase, editorColor);
    dialog.setPalette(dialogPalette);
    dialog.setAutoFillBackground(true);

    auto *layout = new QVBoxLayout(&dialog);
    auto *form = new QFormLayout();
    auto *sourceEdit = new QLineEdit(source, &dialog);
    auto *currentEdit = new QLineEdit(current, &dialog);
    auto *targetEdit = new QLineEdit(current, &dialog);
    auto *typeEdit = new QLineEdit(controlType, &dialog);
    sourceEdit->setReadOnly(true);
    currentEdit->setReadOnly(true);
    typeEdit->setReadOnly(true);
    sourceEdit->setObjectName(QStringLiteral("sp_translation_source"));
    currentEdit->setObjectName(QStringLiteral("sp_translation_current"));
    targetEdit->setObjectName(QStringLiteral("sp_translation_target"));
    typeEdit->setObjectName(QStringLiteral("sp_translation_control_type"));
    form->addRow(QStringLiteral("控件类型："), typeEdit);
    form->addRow(QStringLiteral("原英文："), sourceEdit);
    form->addRow(QStringLiteral("当前翻译："), currentEdit);
    form->addRow(QStringLiteral("新翻译："), targetEdit);
    layout->addLayout(form);

    auto *buttons = new QDialogButtonBox(
        QDialogButtonBox::Save | QDialogButtonBox::Cancel, &dialog);
    buttons->button(QDialogButtonBox::Save)->setText(QStringLiteral("保存"));
    buttons->button(QDialogButtonBox::Cancel)->setText(QStringLiteral("取消"));
    QObject::connect(buttons, &QDialogButtonBox::accepted,
                     &dialog, &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected,
                     &dialog, &QDialog::reject);
    layout->addWidget(buttons);
    targetEdit->selectAll();
    targetEdit->setFocus();

    if (dialog.exec() != QDialog::Accepted)
        return;
    const QString target = targetEdit->text().trimmed();
    if (target.isEmpty() || target == current)
        return;

    QString error;
    if (!saveTranslation(source, target, scopedControlType, &error)) {
        QMessageBox::critical(parent, QStringLiteral("保存翻译失败"), error);
        return;
    }

    // Keep historical reverse entries until restart so widgets currently
    // showing an older translation can still resolve back to the source.
    if (scopedControlType.isEmpty())
        g_translations.insert(source, target);
    else
        g_controlTranslations[scopedControlType].insert(source, target);
    g_originals.insert(target, source);
    refreshTranslatedViews();
}

class TranslationUiFilter final : public QObject {
public:
    using QObject::QObject;
protected:
    bool eventFilter(QObject *object, QEvent *event) override {
        if (!g_enabled)
            return false;
        const auto type = event->type();
        if (type == QEvent::Leave || type == QEvent::Hide) {
            auto *widget = qobject_cast<QWidget *>(object);
            if (widget && g_originalTooltipOwner == widget) {
                QToolTip::hideText();
                g_originalTooltipOwner.clear();
            }
        }
        if (type == QEvent::MouseButtonPress) {
            auto *mouse = static_cast<QMouseEvent *>(event);
            auto *menu = qobject_cast<QMenu *>(object);
            if (menu && mouse->button() == Qt::RightButton &&
                (mouse->modifiers() & Qt::ControlModifier)) {
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
                const QString source = contextSourceAt(menu, mouse->position().toPoint());
#else
                const QString source = contextSourceAt(menu, mouse->pos());
#endif
                if (!source.isEmpty()) {
                    const QString controlType = controlTypeAt(menu);
                    QPointer<QWidget> safeWindow(menu->window());
                    QTimer::singleShot(0, qApp, [source, controlType, safeWindow]() {
                        QWidget *parent = safeWindow.data();
                        if (!parent)
                            parent = QApplication::activeWindow();
                        editTranslation(source, controlType, parent);
                    });
                    event->accept();
                    return true;
                }
            }
        }
        if (type == QEvent::ContextMenu) {
            auto *context = static_cast<QContextMenuEvent *>(event);
            // A plain right-click belongs entirely to Painter. Translation
            // editing is an explicit Ctrl+right-click shortcut so it cannot
            // alter or compete with Painter's native context menus.
            if (!(context->modifiers() & Qt::ControlModifier))
                return false;
            auto *widget = qobject_cast<QWidget *>(object);
            const QString source = contextSourceAt(widget, context->pos());
            if (source.isEmpty())
                return false;
            const QString controlType = controlTypeAt(widget);
            QPointer<QWidget> safeWidget(widget);
            QTimer::singleShot(0, qApp, [source, controlType, safeWidget]() {
                if (safeWidget)
                    editTranslation(source, controlType, safeWidget.data());
            });
            event->accept();
            return true;
        }
        if (type == QEvent::ToolTip) {
            auto *widget = qobject_cast<QWidget *>(object);
            auto *help = static_cast<QHelpEvent *>(event);
            if (shouldSuppressTooltip(widget)) {
                QToolTip::hideText();
                if (g_originalTooltipOwner == widget)
                    g_originalTooltipOwner.clear();
                event->accept();
                return true;
            }
            const QString source = originalTextAt(widget, help->pos());
            if (!source.isNull()) {
                QToolTip::showText(help->globalPos(), source, widget);
                g_originalTooltipOwner = widget;
                event->accept();
                return true;
            }
        }
        // Painter rewrites some parameter labels while a slider is dragged.
        // Paint is the last safe interception point before that English text
        // reaches the screen. translateWidget is idempotent and only calls a
        // setter when the current text actually has a dictionary replacement.
        if (type == QEvent::Paint) {
            // Painter rewrites slider labels and channel buttons during
            // interaction. They need the last-moment paint fallback; other
            // controls are covered by creation and layout events.
            if (auto *widget = qobject_cast<QWidget *>(object)) {
                if (qobject_cast<QLabel *>(widget) ||
                    qobject_cast<QAbstractButton *>(widget) ||
                    isLayerChannelSelector(qobject_cast<QComboBox *>(widget)))
                    translateWidget(widget);
            }
        } else if (type == QEvent::Show || type == QEvent::Polish ||
                   type == QEvent::LayoutRequest ||
                   type == QEvent::ActionAdded) {
            if (auto *widget = qobject_cast<QWidget *>(object))
                translateWidget(widget);
        }
        return false;
    }
};

TranslationUiFilter *g_filter = nullptr;
QTimer *g_fallbackTimer = nullptr;

void scanVisibleWidgets() {
    if (!g_enabled)
        return;
    for (QWidget *widget : QApplication::allWidgets()) {
        if (widget && widget->isVisible())
            translateWidget(widget);
    }
}

bool pinThisDll() {
    HMODULE module = nullptr;
    return GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                 GET_MODULE_HANDLE_EX_FLAG_PIN,
                             reinterpret_cast<LPCWSTR>(&pinThisDll), &module) != 0;
}
} // namespace

extern "C" __declspec(dllexport) int __cdecl sp_delegate_api_version() { return 8; }

extern "C" __declspec(dllexport) void __cdecl sp_delegate_set_translation_path(
    const wchar_t *source, const wchar_t *path) {
    if (!source || !path)
        return;
    g_translationPaths.insert(QString::fromWCharArray(source),
                              QString::fromWCharArray(path));
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_set_fallback_path(
    const wchar_t *path) {
    g_fallbackPath = path ? QString::fromWCharArray(path) : QString();
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_clear_translations() {
    g_translations.clear();
    g_originals.clear();
    g_controlTranslations.clear();
    g_translationPaths.clear();
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_reserve_translations(
    int count) {
    if (count > 0) {
        g_translations.reserve(count);
        g_originals.reserve(count);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_add_translation(
    const wchar_t *source, const wchar_t *target) {
    if (source && target) {
        g_translations.insert(QString::fromWCharArray(source), QString::fromWCharArray(target));
        g_originals.insert(QString::fromWCharArray(target), QString::fromWCharArray(source));
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_set_enabled(int enabled) {
    g_enabled = enabled != 0;
    if (g_enabled)
        scanVisibleWidgets();
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_add_control_translation(
    const wchar_t *controlType, const wchar_t *source, const wchar_t *target) {
    if (controlType && source && target) {
        g_controlTranslations[QString::fromWCharArray(controlType)].insert(
            QString::fromWCharArray(source), QString::fromWCharArray(target));
    }
}

extern "C" __declspec(dllexport) void __cdecl
sp_delegate_set_translate_layers(int enabled) {
    setTranslateLayersPanel(enabled != 0);
}

extern "C" __declspec(dllexport) int __cdecl sp_delegate_install(void *viewPointer) {
    if (!pinThisDll())
        return 0;
    return installAssetDelegate(static_cast<QAbstractItemView *>(viewPointer));
}

extern "C" __declspec(dllexport) int __cdecl sp_delegate_install_ui(void *applicationPointer) {
    if (!pinThisDll())
        return 0;
    auto *application = static_cast<QApplication *>(applicationPointer);
    if (!application)
        application = qobject_cast<QApplication *>(QCoreApplication::instance());
    if (!application)
        return 0;

    // Do not install a QTranslator: translators receive the original English
    // source before Painter's own translator and could therefore override an
    // official Chinese translation. The widget/model display layer below sees
    // Painter's final text and only fills strings that remain untranslated.
    if (!g_filter) {
        g_filter = new TranslationUiFilter(application);
        application->installEventFilter(g_filter);
    }
    if (!g_fallbackTimer) {
        g_fallbackTimer = new QTimer(application);
        g_fallbackTimer->setInterval(10000);
        QObject::connect(g_fallbackTimer, &QTimer::timeout, application, [] { scanVisibleWidgets(); });
        g_fallbackTimer->start();
    }
    scanVisibleWidgets();
    return 1;
}
