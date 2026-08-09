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
#include <QtCore/QSet>
#include <QtCore/QTextStream>
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
#include <QtGui/QTextOption>
#include <QtWidgets/QAbstractButton>
#include <QtWidgets/QAbstractItemView>
#include <QtWidgets/QAbstractScrollArea>
#include <QtWidgets/QAbstractSlider>
#include <QtWidgets/QAbstractSpinBox>
#include <QtWidgets/QApplication>
#include <QtWidgets/QCheckBox>
#include <QtWidgets/QComboBox>
#include <QtWidgets/QDockWidget>
#include <QtWidgets/QDialog>
#include <QtWidgets/QDialogButtonBox>
#include <QtWidgets/QFormLayout>
#include <QtWidgets/QGroupBox>
#include <QtWidgets/QGraphicsObject>
#include <QtWidgets/QGraphicsScene>
#include <QtWidgets/QGraphicsView>
#include <QtWidgets/QHeaderView>
#include <QtWidgets/QLabel>
#include <QtWidgets/QLineEdit>
#include <QtWidgets/QListView>
#include <QtWidgets/QMainWindow>
#include <QtWidgets/QMenu>
#include <QtWidgets/QMenuBar>
#include <QtWidgets/QMessageBox>
#include <QtWidgets/QPushButton>
#include <QtWidgets/QStyledItemDelegate>
#include <QtWidgets/QTabBar>
#include <QtWidgets/QTabWidget>
#include <QtWidgets/QToolButton>
#include <QtWidgets/QToolTip>
#include <QtWidgets/QTreeView>
#include <QtWidgets/QVBoxLayout>

#include <windows.h>
#include <intrin.h>

#include <typeinfo>


namespace {
QHash<QString, QString> g_translations;
QHash<QString, QString> g_originals;
QHash<QString, QHash<QString, QString>> g_controlTranslations;
QHash<QString, QString> g_idTranslations;
QHash<QString, QString> g_translationPaths;
QString g_fallbackPath;
QString g_idTranslationPath;
QPointer<QWidget> g_originalTooltipOwner;
bool g_enabled = true;
bool g_translateLayersPanel = true;
bool g_fuzzyMatchEnabled = true;
QHash<QString, QString> g_fuzzyResolved;
QHash<QString, QString> g_translationsFolded;
QHash<QString, QHash<QString, QString>> g_controlTranslationsFolded;
constexpr auto kSourceProperty = "_sp_translation_source";
constexpr auto kComboSourcesProperty = "_sp_translation_combo_sources";
constexpr auto kTabSourcesProperty = "_sp_translation_tab_sources";
constexpr auto kTranslatingComboProperty = "_sp_translation_combo_busy";

// One Qt6 delegate serves both Painter and Designer. Designer-only features
// (graph-view painting hooks, Designer resource widgets) are always compiled
// in but only activated when the host process is Designer.
bool isDesignerHost() {
    const QString filePath =
        QCoreApplication::applicationFilePath().toLower();
    if (filePath.contains(QStringLiteral("designer")))
        return true;
    const QString appName =
        QCoreApplication::applicationName().toLower();
    return appName.contains(QStringLiteral("designer"));
}

void translateWidget(QWidget *widget);
QString controlUniqueId(QWidget *widget, const QString &sourceText);

// 翻译路径的控件 ID：词库为空时直接返回空，省去每次绘制都计算 ID 的开销；
// 更改翻译窗口的 Ctrl+右键路径仍始终计算完整 ID。
QString translationControlId(QWidget *widget, const QString &sourceText) {
    return g_idTranslations.isEmpty()
               ? QString()
               : controlUniqueId(widget, sourceText);
}

bool containsCjk(const QString &text) {
    for (const QChar character : text) {
        const uint code = character.unicode();
        if ((code >= 0x3400 && code <= 0x4DBF) ||
            (code >= 0x4E00 && code <= 0x9FFF))
            return true;
    }
    return false;
}

bool isAsciiLetter(QChar character) {
    const uint code = character.unicode();
    return (code >= 0x41 && code <= 0x5A) ||
           (code >= 0x61 && code <= 0x7A);
}

bool containsAsciiLetter(const QString &text) {
    for (const QChar character : text) {
        if (isAsciiLetter(character))
            return true;
    }
    return false;
}

void resizeStringList(QStringList &values, int size) {
    while (values.size() < size)
        values.append(QString());
    while (values.size() > size)
        values.removeLast();
}

// Normalization pipeline shared by the dictionary index and every fuzzy
// lookup, following common i18n folding practice:
//   whitespace variants -> collapse  |  invisible chars dropped
//   elision / " *" markers stripped  |  '_' == ' ' (identifier vs label)
//   Unicode NFC                       |  full-width ASCII -> half-width
//   quote/dash variants unified       |  case folding
//   diacritics decomposed and dropped (é -> e)
QString normalizeForMatch(QString text) {
    // Unify whitespace variants (NBSP, figure space, ideographic space, CRLF).
    text.replace(QChar(0x00A0), QLatin1Char(' '));
    text.replace(QChar(0x2007), QLatin1Char(' '));
    text.replace(QChar(0x202F), QLatin1Char(' '));
    text.replace(QChar(0x3000), QLatin1Char(' '));
    text.replace(QLatin1Char('\r'), QLatin1Char('\n'));
    text = text.simplified();

    // Drop invisible characters that never belong to a display name.
    text.remove(QChar(0x200B));  // zero width space
    text.remove(QChar(0x200C));  // zero width non-joiner
    text.remove(QChar(0x200D));  // zero width joiner
    text.remove(QChar(0xFEFF));  // byte order mark
    text.remove(QChar(0x00AD));  // soft hyphen

    // UI state and elision suffixes ("Name …", "Name...", "Name *").
    while (text.endsWith(QChar(0x2026)))
        text.chop(1);
    while (text.endsWith(QLatin1String("...")))
        text.chop(3);
    if (text.endsWith(QLatin1String(" *")))
        text.chop(2);
    text = text.simplified();

    // Identifier <-> display label equivalence ("Color_Dodge" vs "Color dodge").
    text.replace(QLatin1Char('_'), QLatin1Char(' '));
    text = text.simplified();

    // Unicode normalization so composed and decomposed forms match.
    text = text.normalized(QString::NormalizationForm_C);

    // Full-width ASCII (U+FF01..U+FF5E) -> half-width.
    for (int i = 0; i < text.size(); ++i) {
        const uint code = text.at(i).unicode();
        if (code >= 0xFF01 && code <= 0xFF5E)
            text[i] = QChar(code - 0xFEE0);
    }

    // Quote and dash variants.
    text.replace(QChar(0x2018), QLatin1Char('\''));
    text.replace(QChar(0x2019), QLatin1Char('\''));
    text.replace(QChar(0x201C), QLatin1Char('"'));
    text.replace(QChar(0x201D), QLatin1Char('"'));
    text.replace(QChar(0x2010), QLatin1Char('-'));
    text.replace(QChar(0x2011), QLatin1Char('-'));
    text.replace(QChar(0x2012), QLatin1Char('-'));
    text.replace(QChar(0x2013), QLatin1Char('-'));
    text.replace(QChar(0x2014), QLatin1Char('-'));
    text.replace(QChar(0x2015), QLatin1Char('-'));

    // Case folding.
    text = text.toCaseFolded();

    // Diacritics folding: decompose, drop combining marks, recompose.
    text = text.normalized(QString::NormalizationForm_D);
    QString stripped;
    stripped.reserve(text.size());
    for (const QChar ch : text) {
        const QChar::Category category = ch.category();
        if (category == QChar::Mark_NonSpacing ||
            category == QChar::Mark_SpacingCombining ||
            category == QChar::Mark_Enclosing)
            continue;
        stripped.append(ch);
    }
    return stripped.normalized(QString::NormalizationForm_C);
}

// Fuzzy dictionary lookup through the shared normalization pipeline. Callers
// always try the exact map first; this map only exists to catch casing and
// formatting differences ("3D Perlin Noise" vs "3D Perlin noise", "Color_Dodge"
// vs "Color dodge"). Very short strings are too ambiguous to fuzzy-match.
QString fuzzyTranslation(const QString &key) {
    const QString normalized = normalizeForMatch(key);
    if (normalized.size() < 2)
        return {};
    return g_translationsFolded.value(normalized);
}

// Fuzzy lookup across every control-scoped dictionary, used by the unified
// pipeline after the global fuzzy tier. Only exact scoped lookups and exact
// global lookups may run before it, so a scoped fuzzy hit can never override
// a precise entry.
QString anyControlFuzzyTranslation(const QString &key) {
    if (key.isEmpty())
        return {};
    const QString normalized = normalizeForMatch(key);
    if (normalized.size() < 2)
        return {};
    for (auto it = g_controlTranslationsFolded.cbegin();
         it != g_controlTranslationsFolded.cend(); ++it) {
        const auto found = it.value().constFind(normalized);
        if (found != it.value().cend())
            return found.value();
    }
    return {};
}

// Search every control-scoped dictionary. List/tree views have no control
// type of their own, but official-library asset names (Difference, Multiply,
// Overlay, ...) frequently exist only in scoped dictionaries such as
// layer_blend_mode. Exact scoped lookup only; the global exact map and this
// tier both run before any fuzzy lookup.
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

// Paint 等高频路径只沿父链找宿主，不做 allWidgets 全量扫描，避免每次
// 重绘列表都遍历全部控件；Ctrl+右键的精确归属仍走 owningComboBox()。
QComboBox *owningComboBoxFast(QAbstractItemView *view) {
    if (!view)
        return nullptr;
    for (QObject *current = view; current; current = current->parent()) {
        if (auto *combo = qobject_cast<QComboBox *>(current))
            return combo;
    }
    return nullptr;
}

QString translated(const QString &text, bool removeMnemonic = false,
                   const QString &controlId = QString()) {
    // translated() 查找顺序：
//   1. 先识别控件 ID（上级类名||自身类名||自身 objectName||原文），在
    //      id_types_zh.json 中按完整 ID 键精确查找，命中即返回；
    //   2. 全局词库（official/my_assets_zh.json）命中即返回；
    //   3. 全局仍未命中，直接走模糊匹配兜底。
    if (!g_enabled)
        return {};
    QString key = text.trimmed();
    if (key.isEmpty())
        return {};
    // 1. 控件 ID 专属词库（id_types_zh.json，键为完整 ID 字符串）。
    if (!controlId.isEmpty()) {
        const auto idHit = g_idTranslations.constFind(controlId);
        if (idHit != g_idTranslations.cend())
            return idHit.value();
        // 跳过翻译标记：键为“上级类名||自身类名||objectName||*”
        // （* 表示任意原文）、值为 "_skip_"，
        // 表示该控件下任何原文都不翻译（例如导入对话框的
        // QListWidget||QMenu||None||*，避免把 texture 改成纹理破坏导入类型键）。
        // ID 固定为“上级类名||自身类名||objectName||原文”，
        // 原文在最后一段，通配替换最后一段即可。
        const int lastSeparator =
            controlId.lastIndexOf(QStringLiteral("||"));
        if (lastSeparator > 0) {
            const QString wildcard =
                controlId.left(lastSeparator) + QStringLiteral("||*");
            const auto globalWildcard = g_translations.constFind(wildcard);
            if (globalWildcard != g_translations.cend() &&
                globalWildcard.value() == QStringLiteral("_skip_"))
                return {};
            const auto idWildcard = g_idTranslations.constFind(wildcard);
            if (idWildcard != g_idTranslations.cend() &&
                idWildcard.value() == QStringLiteral("_skip_"))
                return {};
        }
    }
    // 全局词库：允许用户映射覆盖官方中文。
    const auto exact = g_translations.constFind(key);
    if (exact != g_translations.cend())
        return exact.value();
    if (containsCjk(key))
        return {};
    // Designer appends " *" to an instance-parameter title as soon as the
    // user overrides its inherited/default value.  The marker is UI state,
    // not part of the translatable source string.  Match the stable title and
    // then preserve the marker in the translated result.
    QString stateSuffix;
    if (key.endsWith(u'*')) {
        key.chop(1);
        key = key.trimmed();
        stateSuffix = QStringLiteral(" *");
    }
    if (removeMnemonic) {
        // Prefer the exact dictionary key (e.g. "R&D"); fall back to the
        // mnemonic-stripped form that Painter actually displays.
        key.remove(u'&');
    }
    // 全局词库（处理 " *" / 助记符后）。
    const auto found = g_translations.constFind(key);
    if (found != g_translations.cend())
        return found.value() + stateSuffix;
    if (g_fuzzyMatchEnabled) {
        const QString fuzzy = fuzzyTranslation(key);
        if (!fuzzy.isNull())
            return fuzzy + stateSuffix;
        const QString scopedFuzzy = anyControlFuzzyTranslation(key);
        if (!scopedFuzzy.isNull())
            return scopedFuzzy + stateSuffix;
    }
    return {};
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
    // 统一顺序：控件 ID（id_types_zh.json）→ 全局词库 → 模糊兜底。
    return translated(source, false,
                      translationControlId(menu, source));
}

class TranslationItemDelegate final : public QStyledItemDelegate {
public:
    explicit TranslationItemDelegate(QAbstractItemView *view,
                                     bool compactGrid = false,
                                     bool layersPanel = false)
        : QStyledItemDelegate(view), compactGrid_(compactGrid),
          layersPanel_(layersPanel), view_(view) {}

    QString displayText(const QVariant &value, const QLocale &locale) const override {
        if (g_enabled && (!layersPanel_ || g_translateLayersPanel) &&
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
            value.metaType().id() == QMetaType::QString) {
#else
            value.userType() == QMetaType::QString) {
#endif
            const QString text = value.toString();
            const QString result = translated(
                text, false, translationControlId(view_, text));
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
    QAbstractItemView *view_ = nullptr;
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

bool isDesignerGraphView(QGraphicsView *view) {
    if (!view)
        return false;
    const QString className =
        QString::fromLatin1(view->metaObject()->className());
    return className ==
               QStringLiteral("Pfx::Editor::Components::Graph::GraphView") ||
           className.endsWith(QStringLiteral("::GraphView"));
}

// The graph's node text is substituted while the view paints, so toggling the
// plug-in must schedule a repaint of every Designer graph view; otherwise the
// previously painted translation (or original) stays on screen.
void refreshGraphViews() {
#if QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    if (QCoreApplication::closingDown())
        return;
#endif
    for (QWidget *widget : QApplication::allWidgets()) {
        if (!widget || !widget->isVisible())
            continue;
        if (auto *view = qobject_cast<QGraphicsView *>(widget)) {
            if (isDesignerGraphView(view) && view->viewport())
                view->viewport()->update();
        }
    }
}

QGraphicsView *designerGraphViewForPainter(QPainter *painter) {
    if (!painter || !painter->device())
        return nullptr;
    // QGraphicsView paints its scene directly on the viewport widget. This
    // identifies that native paint pass without adding or moving scene items.
    auto *viewport = dynamic_cast<QWidget *>(painter->device());
    if (!viewport)
        return nullptr;
    auto *view = qobject_cast<QGraphicsView *>(viewport->parentWidget());
    return isDesignerGraphView(view) && view->viewport() == viewport
               ? view
               : nullptr;
}

bool isDesignerGraphPainter(QPainter *painter) {
    return designerGraphViewForPainter(painter) != nullptr;
}

// graphOwnerItem is defined below together with the other geometry helpers.
QGraphicsItem *graphOwnerItem(QPainter *painter,
                              qreal *differenceOut = nullptr);

// The graph paints node titles that may be elided ("Name …") or shown as the
// raw identifier. The owning item's tooltip carries the full display name on
// its first line, which is the reliable key for the dictionary.
QString stripHtmlTags(QString text) {
    QString plain;
    plain.reserve(text.size());
    bool inTag = false;
    for (const QChar ch : text) {
        if (ch == u'<') {
            inTag = true;
        } else if (ch == u'>') {
            inTag = false;
        } else if (!inTag) {
            plain.append(ch);
        }
    }
    plain.replace(QStringLiteral("&amp;"), QStringLiteral("&"));
    plain.replace(QStringLiteral("&lt;"), QStringLiteral("<"));
    plain.replace(QStringLiteral("&gt;"), QStringLiteral(">"));
    plain.replace(QStringLiteral("&quot;"), QStringLiteral("\""));
    plain.replace(QStringLiteral("&#39;"), QStringLiteral("'"));
    return plain;
}

QString graphFullTitleFromItem(QGraphicsItem *item) {
    for (QGraphicsItem *current = item; current;
         current = current->parentItem()) {
        const QString tip = current->toolTip().trimmed();
        if (tip.isEmpty())
            continue;
        // Designer's tooltip is rich text: "<b>Name</b><br>(ID : ...)…".
        // Take the first segment up to the first line break, then remove the
        // HTML tags so the plain display name can be matched to the dictionary.
        QString firstLine = tip;
        const int htmlBreak =
            firstLine.indexOf(QLatin1String("<br"), 0, Qt::CaseInsensitive);
        if (htmlBreak >= 0)
            firstLine = firstLine.left(htmlBreak);
        const int newline = firstLine.indexOf(QLatin1Char('\n'));
        if (newline >= 0)
            firstLine = firstLine.left(newline);
        firstLine = stripHtmlTags(firstLine).trimmed();
        if (!firstLine.isEmpty())
            return firstLine;
    }
    return {};
}

// Port labels may already be partially translated (mixed CJK + ASCII, e.g.
// "（主要）Background"). When the whole label has no dictionary entry, walk
// the remaining ASCII word segments and translate each one separately. Only
// mixed labels are touched so fully English labels keep their existing
// whole-string lookup behavior.
QString translateMixedPortLabel(const QString &source) {
    bool hasCjk = false;
    bool hasAsciiLetter = false;
    for (const QChar ch : source) {
        const uint code = ch.unicode();
        if ((code >= 0x3400 && code <= 0x4DBF) ||
            (code >= 0x4E00 && code <= 0x9FFF)) {
            hasCjk = true;
        } else if (isAsciiLetter(ch)) {
            hasAsciiLetter = true;
        }
    }
    if (!hasCjk || !hasAsciiLetter)
        return {};

    QString result = source;
    bool changed = false;
    int i = 0;
    while (i < result.size()) {
        if (!isAsciiLetter(result[i])) {
            ++i;
            continue;
        }
        int j = i;
        while (j < result.size()) {
            const uint c = result[j].unicode();
            const bool part =
                (c >= 0x30 && c <= 0x39) ||
                (c >= 0x41 && c <= 0x5A) ||
                (c >= 0x61 && c <= 0x7A) ||
                c == 0x5F;   // underscore keeps identifiers together
            if (!part)
                break;
            ++j;
        }
        const QString word = result.mid(i, j - i);
        QString target = g_translations.value(word);
        if (target.isNull() && g_fuzzyMatchEnabled)
            target = fuzzyTranslation(word);
        if (target.isNull() && g_fuzzyMatchEnabled)
            target = anyControlFuzzyTranslation(word);
        if (!target.isNull() && target != word) {
            result.replace(i, j - i, target);
            changed = true;
            i += target.size();
        } else {
            i = j;
        }
    }
    return changed ? result : QString();
}

QString graphPaintTranslation(QPainter *painter, const QString &source,
                              int portSide = 0) {
    if (!g_enabled)
        return {};
    // 混合端口标签（已部分翻译 + 残留英文，如"（主要） Preview"）需要
    // 放行到分段翻译；纯中文标签才是已翻译完成、直接跳过。
    const bool hasCjk = containsCjk(source);
    const bool mixedPortLabel =
        portSide != 0 && hasCjk && containsAsciiLetter(source);
    if (hasCjk && !mixedPortLabel)
        return {};
    if (!isDesignerGraphPainter(painter))
        return {};
    // 1. Exact dictionary match always wins.
    QString target = g_translations.value(source);
    if (!target.isNull())
        return target;
    const auto cached = g_fuzzyResolved.constFind(source);
    if (cached != g_fuzzyResolved.cend())
        return cached.value();

    // 2. Tooltip full-name fallback (node titles only): the graph paints
    // elided titles ("Name …") and identifier forms. The item tooltip carries
    // the full display name on its first line. Port labels must not use this
    // tooltip match; only node titles are allowed to fall back to it.
    QString cacheKey = source;
    if (portSide == 0) {
        QGraphicsItem *owner = graphOwnerItem(painter);
        if (owner) {
            const QString full = graphFullTitleFromItem(owner);
            const QString fullNormalized = normalizeForMatch(full);
            const QString normalized = normalizeForMatch(source);
            if (!fullNormalized.isEmpty() && fullNormalized != normalized &&
                fullNormalized.startsWith(normalized)) {
                // 同一绘制文本可能属于不同节点（完整名不同），缓存键必须
                // 带上完整名，避免串用其他节点的 tooltip 匹配结果。
                cacheKey = source + QChar(0x01) + fullNormalized;
                const auto tooltipCached =
                    g_fuzzyResolved.constFind(cacheKey);
                if (tooltipCached != g_fuzzyResolved.cend())
                    return tooltipCached.value();
                target = g_translations.value(full);
                if (target.isNull())
                    target = g_translationsFolded.value(fullNormalized);
            }
        }
    }

    // 3. Global and scoped fuzzy matching on the drawn source (case,
    // full-width, underscore, diacritics and whitespace differences). This
    // step is gated by the plug-in option; the tooltip fallback always stays
    // active.
    if (target.isNull() && g_fuzzyMatchEnabled)
        target = fuzzyTranslation(source);
    if (target.isNull() && g_fuzzyMatchEnabled)
        target = anyControlFuzzyTranslation(source);

    // 4. Port labels that are mixed CJK/ASCII: translate the remaining
    // English word segments (e.g. "（主要）Background" -> "（主要）背景").
    if (target.isNull() && portSide != 0)
        target = translateMixedPortLabel(source);

    g_fuzzyResolved.insert(cacheKey, target);
    return target;
}

using DrawPoint = void (*)(QPainter *, const QPoint &, const QString &);
using DrawPointF = void (*)(QPainter *, const QPointF &, const QString &);
using DrawRect = void (*)(QPainter *, const QRect &, int, const QString &,
                          QRect *);
using DrawRectFOption = void (*)(QPainter *, const QRectF &, const QString &,
                                 const QTextOption &);
using DrawXY = void (*)(QPainter *, int, int, const QString &);
using DrawXYWH = void (*)(QPainter *, int, int, int, int, int,
                          const QString &, QRect *);

DrawPoint g_drawPoint = nullptr;
DrawPointF g_drawPointF = nullptr;
DrawRect g_drawRect = nullptr;
DrawRectFOption g_drawRectFOption = nullptr;
DrawXY g_drawXY = nullptr;
DrawXYWH g_drawXYWH = nullptr;
bool g_graphPainterHooksInstalled = false;
QSet<QString> g_graphPaintDiagnosticKeys;

qreal transformDifference(const QTransform &a, const QTransform &b) {
    return qAbs(a.m11() - b.m11()) + qAbs(a.m12() - b.m12()) +
           qAbs(a.m13() - b.m13()) + qAbs(a.m21() - b.m21()) +
           qAbs(a.m22() - b.m22()) + qAbs(a.m23() - b.m23()) +
           qAbs(a.m31() - b.m31()) + qAbs(a.m32() - b.m32()) +
           qAbs(a.m33() - b.m33());
}

QGraphicsItem *graphOwnerItem(QPainter *painter, qreal *differenceOut) {
    QGraphicsView *view = designerGraphViewForPainter(painter);
    if (!view || !view->scene()) {
        if (differenceOut)
            *differenceOut = 1.0e20;
        return nullptr;
    }
    QGraphicsItem *owner = nullptr;
    qreal bestDifference = 1.0e20;
    const QTransform current = painter->worldTransform();
    for (QGraphicsItem *item : view->scene()->items()) {
        if (!item)
            continue;
        const qreal difference = transformDifference(
            current, item->deviceTransform(view->viewportTransform()));
        if (difference < bestDifference) {
            bestDifference = difference;
            owner = item;
        }
    }
    if (differenceOut)
        *differenceOut = bestDifference;
    return owner;
}

#if defined(SD_TRANSLATION_GRAPH_DIAGNOSTICS)
void recordGraphPaintType(QPainter *painter, const QString &text,
                          const char *overload, quintptr caller,
                          int flags = -1) {
    QGraphicsView *view = designerGraphViewForPainter(painter);
    if (!view || !view->scene() || text.isEmpty())
        return;

    qreal bestDifference = 1.0e20;
    QGraphicsItem *owner = graphOwnerItem(painter, &bestDifference);

    const QString ownerRtti = owner
        ? QString::fromLatin1(typeid(*owner).name())
        : QStringLiteral("<none>");
    const QString parentRtti = owner && owner->parentItem()
        ? QString::fromLatin1(typeid(*owner->parentItem()).name())
        : QStringLiteral("<none>");
    const quintptr moduleBase =
        reinterpret_cast<quintptr>(GetModuleHandleW(nullptr));
    const quintptr callerRva = caller >= moduleBase ? caller - moduleBase : 0;
    const QString key = QStringLiteral("%1|%2|%3|%4|%5|%6")
                            .arg(text, QString::fromLatin1(overload), ownerRtti,
                                 parentRtti)
                            .arg(flags)
                            .arg(callerRva, 0, 16);
    if (g_graphPaintDiagnosticKeys.contains(key))
        return;
    g_graphPaintDiagnosticKeys.insert(key);

    QFile output(QDir::temp().filePath(
        QStringLiteral("sd_graph_paint_types.txt")));
    if (!output.open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text))
        return;
    QTextStream stream(&output);
    stream << "text=" << text << "\toverload=" << overload
           << "\tflags=" << flags
           << "\tcaller_rva=0x" << QString::number(callerRva, 16)
           << "\towner_rtti=" << ownerRtti
           << "\towner_public_type=" << (owner ? owner->type() : -1)
           << "\towner_has_parent=" << (owner && owner->parentItem() ? 1 : 0)
           << "\towner_flags=" << (owner ? int(owner->flags()) : -1)
           << "\towner_z=" << (owner ? owner->zValue() : 0.0)
           << "\towner_children=" << (owner ? owner->childItems().size() : -1)
           << "\tparent_rtti=" << parentRtti
           << "\ttransform_difference=" << bestDifference
           << "\tpen=" << painter->pen().color().name(QColor::HexArgb)
           << "\tfont_size=" << painter->font().pointSizeF()
           << "\tfont_weight=" << painter->font().weight() << "\n";
#endif

// Designer's connector items draw each port label centered inside a rectangle
// whose size and position are computed from the original text. Swapping in a
// translation of a different width leaves the text centered inside that stale
// rectangle, so its outer edge no longer lines up with the other port labels.
// Port labels are anchored to the connector dot: input labels end at a fixed
// column just left of the dot (right edge anchored), output labels start at a
// fixed column just right of the dot (left edge anchored). Return +1 for an
// input label, -1 for an output label and 0 when the side cannot be
// determined.
int graphPortLabelSide(QPainter *painter, const QRectF &rect) {
    QGraphicsView *view = designerGraphViewForPainter(painter);
    QGraphicsItem *owner = graphOwnerItem(painter);
    if (!view || !owner || !owner->parentItem())
        return 0;
    const QString rtti = QString::fromLatin1(typeid(*owner).name());
    if (!rtti.contains(QStringLiteral("Connector")))
        return 0;
    const QRectF nodeRect = owner->parentItem()->sceneBoundingRect();
    if (nodeRect.width() <= 0.0)
        return 0;
    const qreal labelCenterX = painter->worldTransform().map(rect.center()).x();
    const qreal nodeCenterX = view->mapFromScene(nodeRect.center()).x();
    if (labelCenterX + 2.0 < nodeCenterX)
        return 1;   // label on the left half of the node: input port
    if (labelCenterX - 2.0 > nodeCenterX)
        return -1;  // label on the right half of the node: output port
    return 0;
}

Qt::Alignment graphPortLabelAlignment(Qt::Alignment alignment,
                                      int portSide) {
    alignment &= ~Qt::AlignHorizontal_Mask;
    if (portSide == 1)
        alignment |= Qt::AlignRight;   // input label: right edge meets the dot
    else if (portSide == -1)
        alignment |= Qt::AlignLeft;    // output label: left edge leaves the dot
    else
        alignment |= Qt::AlignHCenter;
    return alignment;
}

void hookedDrawPoint(QPainter *painter, const QPoint &point,
                     const QString &text) {
#if defined(SD_TRANSLATION_GRAPH_DIAGNOSTICS)
    recordGraphPaintType(painter, text, "QPoint",
                         reinterpret_cast<quintptr>(_ReturnAddress()));
#endif
    const QString target = graphPaintTranslation(painter, text);
    g_drawPoint(painter, point, target.isEmpty() ? text : target);
}

void hookedDrawPointF(QPainter *painter, const QPointF &point,
                      const QString &text) {
#if defined(SD_TRANSLATION_GRAPH_DIAGNOSTICS)
    recordGraphPaintType(painter, text, "QPointF",
                         reinterpret_cast<quintptr>(_ReturnAddress()));
#endif
    const QString target = graphPaintTranslation(painter, text);
    g_drawPointF(painter, point, target.isEmpty() ? text : target);
}

void hookedDrawRect(QPainter *painter, const QRect &rect, int flags,
                    const QString &text, QRect *boundingRect) {
#if defined(SD_TRANSLATION_GRAPH_DIAGNOSTICS)
    recordGraphPaintType(painter, text, "QRect",
                         reinterpret_cast<quintptr>(_ReturnAddress()), flags);
#endif
    const QString target = graphPaintTranslation(painter, text);
    g_drawRect(painter, rect, flags, target.isEmpty() ? text : target,
               boundingRect);
}

void hookedDrawRectFOption(QPainter *painter, const QRectF &rect,
                           const QString &text,
                           const QTextOption &option) {
#if defined(SD_TRANSLATION_GRAPH_DIAGNOSTICS)
    recordGraphPaintType(painter, text, "QRectF/QTextOption",
                         reinterpret_cast<quintptr>(_ReturnAddress()),
                         int(option.alignment()) |
                             (int(option.textDirection()) << 16));
#endif
    const int portSide = graphPortLabelSide(painter, rect);
    const QString target = graphPaintTranslation(painter, text, portSide);
    if (target.isEmpty()) {
        g_drawRectFOption(painter, rect, text, option);
        return;
    }
    if (portSide == 0) {
        g_drawRectFOption(painter, rect, target, option);
        return;
    }
    QTextOption drawOption(option);
    drawOption.setWrapMode(QTextOption::NoWrap);
    drawOption.setAlignment(graphPortLabelAlignment(option.alignment(),
                                                    portSide));
    g_drawRectFOption(painter, rect, target, drawOption);
}

void hookedDrawXY(QPainter *painter, int x, int y, const QString &text) {
#if defined(SD_TRANSLATION_GRAPH_DIAGNOSTICS)
    recordGraphPaintType(painter, text, "XY",
                         reinterpret_cast<quintptr>(_ReturnAddress()));
#endif
    const QString target = graphPaintTranslation(painter, text);
    g_drawXY(painter, x, y, target.isEmpty() ? text : target);
}

void hookedDrawXYWH(QPainter *painter, int x, int y, int width, int height,
                    int flags, const QString &text, QRect *boundingRect) {
#if defined(SD_TRANSLATION_GRAPH_DIAGNOSTICS)
    recordGraphPaintType(painter, text, "XYWH",
                         reinterpret_cast<quintptr>(_ReturnAddress()), flags);
#endif
    const QString target = graphPaintTranslation(painter, text);
    g_drawXYWH(painter, x, y, width, height, flags,
               target.isEmpty() ? text : target, boundingRect);
}

bool replaceMainModuleImport(void *original, void *replacement) {
    if (!original || !replacement)
        return false;
    auto *base = reinterpret_cast<unsigned char *>(GetModuleHandleW(nullptr));
    if (!base)
        return false;
    auto *dos = reinterpret_cast<IMAGE_DOS_HEADER *>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return false;
    auto *nt = reinterpret_cast<IMAGE_NT_HEADERS *>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE)
        return false;
    const DWORD importRva = nt->OptionalHeader
        .DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!importRva)
        return false;
    bool replaced = false;
    auto *descriptor =
        reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR *>(base + importRva);
    for (; descriptor->Name; ++descriptor) {
        if (!descriptor->FirstThunk)
            continue;
        auto *thunk = reinterpret_cast<IMAGE_THUNK_DATA *>(
            base + descriptor->FirstThunk);
        for (; thunk->u1.Function; ++thunk) {
            auto **slot = reinterpret_cast<void **>(&thunk->u1.Function);
            if (*slot != original)
                continue;
            DWORD oldProtection = 0;
            if (!VirtualProtect(slot, sizeof(void *), PAGE_READWRITE,
                                &oldProtection))
                continue;
            *slot = replacement;
            DWORD ignored = 0;
            VirtualProtect(slot, sizeof(void *), oldProtection, &ignored);
            FlushInstructionCache(GetCurrentProcess(), slot, sizeof(void *));
            replaced = true;
        }
    }
    return replaced;
}

template <typename Function>
bool hookQtGuiImport(HMODULE qtGui, const char *symbol, Function hook,
                     Function &original) {
    original = reinterpret_cast<Function>(GetProcAddress(qtGui, symbol));
    return original && replaceMainModuleImport(
        reinterpret_cast<void *>(original), reinterpret_cast<void *>(hook));
}

bool installGraphPainterHooks() {
    if (g_graphPainterHooksInstalled)
        return true;
    HMODULE qtGui = GetModuleHandleW(L"Qt6Gui.dll");
    if (!qtGui)
        return false;
    bool installed = false;
    installed |= hookQtGuiImport(
        qtGui, "?drawText@QPainter@@QEAAXAEBVQPoint@@AEBVQString@@@Z",
        &hookedDrawPoint, g_drawPoint);
    installed |= hookQtGuiImport(
        qtGui, "?drawText@QPainter@@QEAAXAEBVQPointF@@AEBVQString@@@Z",
        &hookedDrawPointF, g_drawPointF);
    installed |= hookQtGuiImport(
        qtGui,
        "?drawText@QPainter@@QEAAXAEBVQRect@@HAEBVQString@@PEAV2@@Z",
        &hookedDrawRect, g_drawRect);
    installed |= hookQtGuiImport(
        qtGui,
        "?drawText@QPainter@@QEAAXAEBVQRectF@@AEBVQString@@AEBVQTextOption@@@Z",
        &hookedDrawRectFOption, g_drawRectFOption);
    installed |= hookQtGuiImport(
        qtGui, "?drawText@QPainter@@QEAAXHHAEBVQString@@@Z",
        &hookedDrawXY, g_drawXY);
    installed |= hookQtGuiImport(
        qtGui,
        "?drawText@QPainter@@QEAAXHHHHHAEBVQString@@PEAVQRect@@@Z",
        &hookedDrawXYWH, g_drawXYWH);
    g_graphPainterHooksInstalled = installed;
    return installed;
}

bool isDesignerResourceList(QAbstractItemView *view) {
    if (!view || !view->model())
        return false;
    const QString viewClass =
        QString::fromLatin1(view->metaObject()->className());
    const QString modelClass =
        QString::fromLatin1(view->model()->metaObject()->className());
    return viewClass ==
               QStringLiteral("Pfx::DataBase::ResourceTableWidget::CustomListView") &&
           modelClass == QStringLiteral("Pfx::DataBase::ResourcesListModel");
}

bool isDesignerLibraryTree(QAbstractItemView *view) {
    if (!view || !view->model() ||
        view->objectName() != QStringLiteral("mTreeWidget"))
        return false;
    if (QString::fromLatin1(view->model()->metaObject()->className()) !=
        QStringLiteral("QTreeModel"))
        return false;
    for (QObject *parent = view->parent(); parent; parent = parent->parent()) {
        if (QString::fromLatin1(parent->metaObject()->className()) ==
            QStringLiteral("Pfx::Editor::Components::Shelf::QueryExplorerWidget"))
            return true;
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
        const QString result = translated(source, true,
                                          translationControlId(menu, source));
        if (!result.isNull() && action->text() != result) {
            action->setProperty(kSourceProperty, source);
            action->setText(result);
        }
    }
}

void translateMenuBar(QMenuBar *menuBar) {
    if (!menuBar || !g_enabled)
        return;
    for (QAction *action : menuBar->actions()) {
        const QString source = actionSource(action);
        const QString result = translated(source, true,
                                          translationControlId(menuBar, source));
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
        qobject_cast<QMenuBar *>(widget) ||
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
        if (isDesignerResourceList(itemView) ||
            isDesignerLibraryTree(itemView)) {
            installAssetDelegate(itemView);
            return;
        }
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
    if (auto *menuBar = qobject_cast<QMenuBar *>(widget)) {
        translateMenuBar(menuBar);
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
        const QString result = translated(source, true,
                                          translationControlId(widget, source));
        if (!result.isNull() && button->text() != result) {
            button->setProperty(kSourceProperty, source);
            button->setText(result);
        }
        return;
    }
    if (auto *label = qobject_cast<QLabel *>(widget)) {
        const QString source = sourceForObject(label, label->text());
        const QString result = translated(source, true,
                                          translationControlId(widget, source));
        if (!result.isNull() && label->text() != result) {
            label->setProperty(kSourceProperty, source);
            label->setText(result);
        }
        return;
    }
    if (auto *group = qobject_cast<QGroupBox *>(widget)) {
        const QString source = sourceForObject(group, group->title());
        const QString result = translated(source, false,
                                          translationControlId(widget, source));
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
        for (int i = 0; i < combo->count(); ++i) {
            const QString source = comboSourceAt(combo, i);
            const QString result = translated(source, false,
                                              translationControlId(combo, source));
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
            const QString result = translated(source, false,
                                              translationControlId(tabs, source));
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
        const QString result = translated(source, false,
                                          translationControlId(widget, source));
        if (!result.isNull() && dock->windowTitle() != result) {
            dock->setProperty(kSourceProperty, source);
            dock->setWindowTitle(result);
        }
        return;
    }
    if (auto *lineEdit = qobject_cast<QLineEdit *>(widget)) {
        const QString source = sourceForObject(lineEdit, lineEdit->placeholderText());
        const QString result = translated(source, false,
                                          translationControlId(widget, source));
        if (!result.isNull() && lineEdit->placeholderText() != result) {
            lineEdit->setProperty(kSourceProperty, source);
            lineEdit->setPlaceholderText(result);
        }
    }
}

QString originalTextAt(QWidget *widget, const QPoint &position) {
    if (!widget || !g_enabled)
        return {};

    // Color editors are composite controls and may deliver the tooltip event
    // through an internal QLabel/QWidget rather than Alg::ColorButton itself.
    // Never replace Painter's color-editing hover behaviour with an English
    // original-text hint.
    for (QObject *current = widget; current; current = current->parent()) {
        const QString className =
            QString::fromLatin1(current->metaObject()->className());
        const QString objectName = current->objectName();
        if (className == QStringLiteral("Alg::ColorButton") ||
            className.contains(QStringLiteral("ColorPicker"),
                               Qt::CaseInsensitive) ||
            className.contains(QStringLiteral("ColorEditor"),
                               Qt::CaseInsensitive) ||
            objectName == QStringLiteral("colorZone"))
            return {};
        if (className == QStringLiteral("Alg::AbstractDataView"))
            break;
    }

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
                    const QString expected = translated(
                        source, false,
                        translationControlId(combo, source));
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
    else if (auto *menuBar = qobject_cast<QMenuBar *>(widget)) {
        QAction *action = menuBar->actionAt(position);
        if (!action)
            return {};
        displayed = action->text();
    }
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
    // A QDockWidget covers its complete panel, including large blank content
    // areas. Treating its window title as text under the cursor therefore
    // produced an unrelated tooltip (for example "Properties - Fill") almost
    // anywhere inside the properties panel. The real title-bar label is a
    // separate child widget and is handled by the QLabel path above.
    else if (qobject_cast<QDockWidget *>(widget))
        return {};

    displayed.remove(u'&');
    displayed = displayed.trimmed();
    const auto found = g_originals.constFind(displayed);
    return found == g_originals.cend() ? QString() : found.value();
}

bool shouldSuppressTooltip(QWidget *widget) {
    if (!widget)
        return false;

    // Apply this test before the QLabel exception below. Painter's color
    // control contains label-like children, and those children must not revive
    // the plug-in's original-text tooltip while the color swatch is hovered.
    for (QObject *current = widget; current; current = current->parent()) {
        const QString className =
            QString::fromLatin1(current->metaObject()->className());
        const QString objectName = current->objectName();
        if (className == QStringLiteral("Alg::ColorButton") ||
            className.contains(QStringLiteral("ColorPicker"),
                               Qt::CaseInsensitive) ||
            className.contains(QStringLiteral("ColorEditor"),
                               Qt::CaseInsensitive) ||
            objectName == QStringLiteral("colorZone"))
            return true;
        if (className == QStringLiteral("Alg::AbstractDataView"))
            break;
    }

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
                    if (original != g_originals.cend())
                        return original.value();
                    // 原文已是中文（或未命中词库）时也允许弹窗，
                    // 否则下拉框弹出项 Ctrl+右键会没有反应。
                    return displayed;
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
        // Chinese text without our marker is official localization. Allow the
        // editor to inspect it; editTranslation() will show a warning.
        if (containsCjk(displayed))
            return displayed.trimmed();
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
    // Dock widgets span the whole panel. Their window title is not a discrete
    // text control under the cursor, so editing it would also trigger when the
    // user Ctrl+right-clicks an unrelated blank area of the panel.
    else if (qobject_cast<QDockWidget *>(widget))
        return {};

    displayed.remove(u'&');
    displayed = displayed.trimmed();
    const QString storedSource = widget->property(kSourceProperty).toString();
    if (!storedSource.isEmpty() && g_translations.value(storedSource) == displayed)
        return storedSource;
    const auto original = g_originals.constFind(displayed);
    if (original != g_originals.cend())
        return original.value();
    if (containsCjk(displayed))
        return displayed;
    return displayed;
}

// 控件所属面板（广义：QDockWidget 或 QDialog/顶层窗口）：
// 同时返回 objectName 和窗口标题，缺省用 None 占位。
QString controlPanelName(QWidget *widget) {
    if (!widget)
        return {};
    QWidget *target = nullptr;
    for (QWidget *current = widget; current;
         current = current->parentWidget()) {
        if (auto *dock = qobject_cast<QDockWidget *>(current)) {
            target = dock;
            break;
        }
        if (current->isWindow()) {
            // 弹出菜单/下拉弹出层本身是无标题的临时窗口，
            // 继续沿父级往上找真正的宿主窗口（QDialog/QMainWindow）。
            const bool isPopup =
                current->windowType() == Qt::Popup ||
                current->windowType() == Qt::ToolTip;
            const bool hasTitle =
                !current->windowTitle().trimmed().isEmpty();
            if (!isPopup &&
                (hasTitle || qobject_cast<QDialog *>(current) ||
                 qobject_cast<QMainWindow *>(current))) {
                target = current;
                break;
            }
            if (!current->parentWidget())
                break;
        }
    }
    if (!target)
        target = widget->window();
    if (!target)
        return {};
    const QString objectName = target->objectName();
    const QString windowTitle = target->windowTitle().trimmed();
    return QStringLiteral("objectName：%1，窗口标题：%2")
        .arg(objectName.isEmpty() ? QStringLiteral("None") : objectName)
        .arg(windowTitle.isEmpty() ? QStringLiteral("None") : windowTitle);
}

QString controlUniqueId(QWidget *widget, const QString &sourceText) {
    // 返回用于生成稳定 ID 的规范字符串：
// 上级类名||自身类名||自身 objectName||原文，
// 上级类名指被点击控件上级控件（parentWidget）的类名，
    // 自身指被点击控件本身；哪一项没有就用 None 占位。
    if (!widget)
        return {};

    const QString parentClassName =
        widget->parentWidget()
            ? QString::fromLatin1(
                  widget->parentWidget()->metaObject()->className())
            : QString();
    const QString ownClassName =
        QString::fromLatin1(widget->metaObject()->className());
    const QString ownObjectName = widget->objectName();
    // 菜单/按钮文本可能带助记符 "&"，词库键统一用去掉助记符的原文。
    QString normalizedSource = sourceText;
    normalizedSource.remove(u'&');

    auto orNone = [](const QString &value) {
        return value.isEmpty() ? QStringLiteral("None") : value;
    };
return orNone(parentClassName) + QStringLiteral("||")
    + orNone(ownClassName) + QStringLiteral("||")
    + orNone(ownObjectName) + QStringLiteral("||")
    + orNone(normalizedSource);
}

bool saveTranslation(const QString &source, const QString &target,
                     const QString &controlType, QString *error,
                     const QString &fixedPath = QString()) {
    const QString translationPath = fixedPath.isEmpty()
        ? g_translationPaths.value(source, g_fallbackPath)
        : fixedPath;
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
    if (auto *menuBar = qobject_cast<QMenuBar *>(widget)) {
        for (QAction *action : menuBar->actions()) {
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

void restoreLayersPanelOriginals() {
#if QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    if (QCoreApplication::closingDown())
        return;
#endif
    for (QWidget *widget : QApplication::allWidgets()) {
        if (widget && isInsideLayersPanel(widget))
            restoreTranslatedWidget(widget);
    }
}

void restoreAllTranslatedWidgets() {
#if QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    if (QCoreApplication::closingDown())
        return;
#endif
    for (QWidget *widget : QApplication::allWidgets()) {
        if (widget)
            restoreTranslatedWidget(widget);
    }
}

void setTranslateLayersPanel(bool enabled) {
    if (g_translateLayersPanel == enabled)
        return;
    g_translateLayersPanel = enabled;
    if (enabled) {
        refreshTranslatedViews();
        return;
    }
    restoreLayersPanelOriginals();
}

// 主窗口怎么设置 UI 风格，所有插件弹窗就怎么设置：统一继承主窗口的调色板、
// 样式表、字体和图标，保证与软件主界面外观一致。
QWidget *hostStyleWindow(QWidget *reference) {
    QWidget *host = reference ? reference->window() : nullptr;
    if (!host)
        host = QApplication::activeWindow();
    if (!host) {
        const QWidgetList topLevel = QApplication::topLevelWidgets();
        for (QWidget *widget : topLevel) {
            if (widget->isVisible()) {
                host = widget;
                break;
            }
        }
    }
    return host;
}

void applyHostWindowStyle(QWidget *window, QWidget *reference) {
    if (!window)
        return;
    QWidget *host = hostStyleWindow(reference);
    if (host) {
        window->setPalette(host->palette());
        window->setStyleSheet(host->styleSheet());
        window->setFont(host->font());
        window->setWindowIcon(host->windowIcon());
    }
    if (window->windowIcon().isNull())
        window->setWindowIcon(QApplication::windowIcon());
}

void showHostMessage(QWidget *parent, const QString &title,
                     const QString &text,
                     QMessageBox::Icon icon = QMessageBox::Information) {
    QMessageBox box(parent);
    box.setWindowTitle(title);
    box.setText(text);
    box.setIcon(icon);
    applyHostWindowStyle(&box, parent);
    box.exec();
}

// 自定义 ID 的悬停注释：原生 ToolTip 会按宽度自动换行，这里用自绘
// QLabel（默认不换行）保证注释始终显示在一行。
class IdTipFilter final : public QObject {
public:
    explicit IdTipFilter(QObject *parent = nullptr) : QObject(parent) {}

    QLabel *tip = nullptr;
    QWidget *field = nullptr;

    bool eventFilter(QObject *object, QEvent *event) override {
        if (object != field)
            return false;
        if (event->type() == QEvent::Enter) {
            if (tip) {
                tip->adjustSize();
                tip->move(field->mapToGlobal(
                    QPoint(0, -tip->height() - 4)));
                tip->show();
                tip->raise();
            }
        } else if (event->type() == QEvent::Leave) {
            if (tip)
                tip->hide();
        }
        return false;
    }
};

void editTranslation(const QString &source, const QString &uniqueId,
                     const QString &panelName, QWidget *parent) {
    if (source.isEmpty())
        return;
    QString scopedControlType;
    QString current = g_idTranslations.value(uniqueId);
    if (current.isNull())
        current = g_translations.value(source);
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
    applyHostWindowStyle(&dialog, dialogParent);

    auto *layout = new QVBoxLayout(&dialog);
    auto *form = new QFormLayout();
    auto *sourceEdit = new QLineEdit(source, &dialog);
    auto *currentEdit = new QLineEdit(current, &dialog);
    auto *targetEdit = new QLineEdit(current, &dialog);
    auto *uniqueIdEdit = new QLineEdit(uniqueId, &dialog);
    sourceEdit->setReadOnly(true);
    currentEdit->setReadOnly(true);
    uniqueIdEdit->setReadOnly(true);
    sourceEdit->setObjectName(QStringLiteral("sp_translation_source"));
    currentEdit->setObjectName(QStringLiteral("sp_translation_current"));
    targetEdit->setObjectName(QStringLiteral("sp_translation_target"));
    uniqueIdEdit->setObjectName(QStringLiteral("sp_translation_unique_id"));
    auto *idTip = new QLabel(
        QStringLiteral(
            "自定义 ID 格式：上级控件类名||自身控件类名||自身控件objectName||原文"),
        &dialog);
    idTip->setObjectName(QStringLiteral("sp_translation_id_tip"));
    idTip->setWindowFlags(Qt::ToolTip);
    idTip->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    idTip->setStyleSheet(QStringLiteral(
        "QLabel { background: #2b2b2b; color: #ffffff;"
        " padding: 4px 8px; border: 1px solid #555555; }"));
    idTip->hide();
    auto *idTipFilter = new IdTipFilter(idTip);
    idTipFilter->tip = idTip;
    idTipFilter->field = uniqueIdEdit;
    uniqueIdEdit->installEventFilter(idTipFilter);
    auto *panelEdit = new QLineEdit(
        panelName.isEmpty() ? QStringLiteral("None") : panelName, &dialog);
    panelEdit->setReadOnly(true);
    panelEdit->setObjectName(QStringLiteral("sp_translation_panel_name"));
    form->addRow(QStringLiteral("自定义ID："), uniqueIdEdit);
    form->addRow(QStringLiteral("所属面板："), panelEdit);
    form->addRow(QStringLiteral("原文："), sourceEdit);
    form->addRow(QStringLiteral("当前翻译："), currentEdit);
    form->addRow(QStringLiteral("新翻译："), targetEdit);
    layout->addLayout(form);

    auto *idCheck = new QCheckBox(
        QStringLiteral("保存到专项词库（control_ids_zh.json）"), &dialog);
    idCheck->setObjectName(QStringLiteral("sp_translation_save_to_id"));
    layout->addWidget(idCheck);

    if (containsCjk(source)) {
        auto *warning = new QLabel(
            QStringLiteral("这是软件官方提供的中文，不建议更改。保存后将由插件词库覆盖官方中文。"),
            &dialog);
        warning->setObjectName(QStringLiteral("sp_translation_official_warning"));
        warning->setWordWrap(true);
        warning->setStyleSheet(QStringLiteral(
            "QLabel { color: #ff5c5c; font-weight: 600; padding: 4px 0; }"));
        layout->addWidget(warning);
    }

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
    if (target.isEmpty() || target == current) {
        showHostMessage(parent, QStringLiteral("提示"),
                        QStringLiteral("翻译未改变，未写入词库"));
        return;
    }

    QString error;
    const bool saveToId = idCheck->isChecked() && !uniqueId.isEmpty();
    if (saveToId) {
        // 保存到专项词库：以完整控件 ID 为键写入 control_ids_zh.json。
        if (!saveTranslation(uniqueId, target, QString(), &error,
                             g_idTranslationPath)) {
            showHostMessage(parent, QStringLiteral("保存翻译失败"), error,
                            QMessageBox::Critical);
            return;
        }
        g_idTranslations.insert(uniqueId, target);
    } else {
        if (!saveTranslation(source, target, scopedControlType, &error)) {
            showHostMessage(parent, QStringLiteral("保存翻译失败"), error,
                            QMessageBox::Critical);
            return;
        }
        // Keep historical reverse entries until restart so widgets currently
        // showing an older translation can still resolve back to the source.
        if (scopedControlType.isEmpty())
            g_translations.insert(source, target);
        else
            g_controlTranslations[scopedControlType].insert(source, target);
        g_originals.insert(target, source);
    }
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
                const QPoint mousePos = mouse->position().toPoint();
#else
                const QPoint mousePos = mouse->pos();
#endif
                const QString source = contextSourceAt(menu, mousePos);
                if (!source.isEmpty()) {
                    const QString uniqueId = controlUniqueId(menu, source);
                    const QString panelName = controlPanelName(menu);
                    QPointer<QWidget> safeWindow(menu->window());
                    QTimer::singleShot(
                        0, qApp,
                        [source, uniqueId, panelName, safeWindow]() {
                        QWidget *parent = safeWindow.data();
                        if (!parent)
                            parent = QApplication::activeWindow();
                        editTranslation(source, uniqueId, panelName, parent);
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
            const QString uniqueId = controlUniqueId(widget, source);
            const QString panelName = controlPanelName(widget);
            QPointer<QWidget> safeWidget(widget);
            QTimer::singleShot(
                0, qApp,
                [source, uniqueId, panelName, safeWidget]() {
                if (safeWidget)
                    editTranslation(source, uniqueId, panelName,
                                    safeWidget.data());
            });
            event->accept();
            return true;
        }
        if (type == QEvent::ToolTip) {
            auto *widget = qobject_cast<QWidget *>(object);
            auto *help = static_cast<QHelpEvent *>(event);
            // 插件自己的“更改翻译”弹窗放行原生 ToolTip（自定义 ID 的
            // 悬停注释），其余控件按原有规则抑制。
            const bool isPluginDialogWidget =
                widget && widget->objectName().startsWith(
                    QStringLiteral("sp_translation_"));
            if (shouldSuppressTooltip(widget) && !isPluginDialogWidget) {
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
        // The host rewrites some parameter labels while a value is edited.
        // Paint is the last safe interception point before that English text
        // reaches the screen. translateWidget is idempotent and only calls a
        // setter when the current text actually has a dictionary replacement.
        if (type == QEvent::Paint) {
            if (auto *widget = qobject_cast<QWidget *>(object)) {
                if (qobject_cast<QLabel *>(widget) ||
                    qobject_cast<QAbstractButton *>(widget) ||
                    qobject_cast<QComboBox *>(widget)) {
                    translateWidget(widget);
                } else if (auto *view =
                               qobject_cast<QAbstractItemView *>(widget)) {
                    if (QComboBox *combo = owningComboBoxFast(view))
                        translateWidget(combo);
                }
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
#if QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    if (QCoreApplication::closingDown())
        return;
#endif
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

extern "C" __declspec(dllexport) int __cdecl sp_delegate_api_version() { return 10; }

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

extern "C" __declspec(dllexport) void __cdecl sp_delegate_set_id_path(
    const wchar_t *path) {
    g_idTranslationPath = path ? QString::fromWCharArray(path) : QString();
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_clear_translations() {
    g_translations.clear();
    g_originals.clear();
    g_controlTranslations.clear();
    g_controlTranslationsFolded.clear();
    g_idTranslations.clear();
    g_translationPaths.clear();
    g_fuzzyResolved.clear();
    g_translationsFolded.clear();
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_set_fuzzy_match(
    int enabled) {
    g_fuzzyMatchEnabled = enabled != 0;
    g_fuzzyResolved.clear();
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_reserve_translations(
    int count) {
    if (count > 0) {
        g_translations.reserve(count);
        g_originals.reserve(count);
        g_translationsFolded.reserve(count);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_add_translation(
    const wchar_t *source, const wchar_t *target) {
    if (source && target) {
        const QString sourceString = QString::fromWCharArray(source);
        const QString targetString = QString::fromWCharArray(target);
        g_translations.insert(sourceString, targetString);
        g_translationsFolded.insert(normalizeForMatch(sourceString),
                                    targetString);
        g_originals.insert(targetString, sourceString);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_set_enabled(int enabled) {
    g_enabled = enabled != 0;
    if (g_enabled) {
        scanVisibleWidgets();
    } else {
        // Disabling the plug-in must immediately restore every widget that
        // was translated by this delegate back to its original text.
        restoreAllTranslatedWidgets();
    }
    refreshGraphViews();
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_add_control_translation(
    const wchar_t *controlType, const wchar_t *source, const wchar_t *target) {
    if (controlType && source && target) {
        const QString controlTypeString = QString::fromWCharArray(controlType);
        const QString sourceString = QString::fromWCharArray(source);
        const QString targetString = QString::fromWCharArray(target);
        g_controlTranslations[controlTypeString].insert(sourceString,
                                                        targetString);
        g_controlTranslationsFolded[controlTypeString].insert(
            normalizeForMatch(sourceString), targetString);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_add_id_translation(
    const wchar_t *id, const wchar_t *target) {
    if (id && target) {
        g_idTranslations.insert(QString::fromWCharArray(id),
                                QString::fromWCharArray(target));
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

    // Designer's private graph item paints its title directly; there is no
    // public text child to edit. Patch only the host's imported QPainter
    // drawText calls and substitute exact, currently visible node titles.
    // Geometry, font, clipping and z-order therefore remain entirely native.
    // The hook is installed only when the host is Designer; in Painter the
    // universal Qt6 delegate runs without patching any Qt painting calls.
    if (isDesignerHost())
        installGraphPainterHooks();

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
