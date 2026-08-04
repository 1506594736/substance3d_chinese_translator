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
#include <QtGui/QAction>
#include <QtGui/QPainter>
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
#include <QtWidgets/QToolTip>
#include <QtWidgets/QTreeView>
#include <QtWidgets/QVBoxLayout>

#include <windows.h>

namespace {
QHash<QString, QString> g_translations;
QHash<QString, QString> g_originals;
QHash<QString, QString> g_translationPaths;
bool g_enabled = true;
constexpr auto kSourceProperty = "_sp_translation_source";

QString translated(const QString &text, bool removeMnemonic = false) {
    if (!g_enabled)
        return {};
    QString key = text.trimmed();
    if (removeMnemonic)
        key.remove(u'&');
    // Painter's own localization wins. Never reinterpret or overwrite text
    // that the host application already presents in Chinese.
    for (const QChar character : key) {
        const uint code = character.unicode();
        if ((code >= 0x3400 && code <= 0x4DBF) ||
            (code >= 0x4E00 && code <= 0x9FFF))
            return {};
    }
    // A widget may still contain the previous Chinese translation after a
    // live edit. Resolve it back to the English source before looking up the
    // latest value so changes appear immediately without restarting Painter.
    const auto original = g_originals.constFind(key);
    if (original != g_originals.cend())
        key = original.value();
    const auto found = g_translations.constFind(key);
    return found == g_translations.cend() ? QString() : found.value();
}

bool isInsideLayersPanel(QWidget *widget) {
    for (QObject *parent = widget ? widget->parent() : nullptr; parent; parent = parent->parent()) {
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

class NativeAssetDelegate final : public QStyledItemDelegate {
public:
    explicit NativeAssetDelegate(QAbstractItemView *view, bool compactGrid = false)
        : QStyledItemDelegate(view), compactGrid_(compactGrid) {}

    QString displayText(const QVariant &value, const QLocale &locale) const override {
        if (g_enabled && value.metaType().id() == QMetaType::QString) {
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
};

int installAssetDelegate(QAbstractItemView *view, bool compactGrid = false) {
    if (!view)
        return 0;
    if (dynamic_cast<NativeAssetDelegate *>(view->itemDelegate())) {
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
    view->setItemDelegate(new NativeAssetDelegate(view, compactGrid));
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
    for (QAction *action : menu->actions()) {
        const QString result = translated(action->text(), true);
        if (!result.isNull() && action->text() != result)
            action->setText(result);
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
    if (!supportedType || isInsideLayersPanel(widget))
        return;

    const QString className = QString::fromLatin1(widget->metaObject()->className());
    if (auto *itemView = qobject_cast<QAbstractItemView *>(widget)) {
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
        QString source = button->text().trimmed();
        source.remove(u'&');
        const QString result = translated(source, true);
        if (!result.isNull() && button->text() != result) {
            button->setProperty(kSourceProperty, source);
            button->setText(result);
        }
        return;
    }
    if (auto *label = qobject_cast<QLabel *>(widget)) {
        QString source = label->text().trimmed();
        source.remove(u'&');
        const QString result = translated(source, true);
        if (!result.isNull() && label->text() != result) {
            label->setProperty(kSourceProperty, source);
            label->setText(result);
        }
        return;
    }
    if (auto *group = qobject_cast<QGroupBox *>(widget)) {
        const QString source = group->title().trimmed();
        const QString result = translated(source);
        if (!result.isNull() && group->title() != result) {
            group->setProperty(kSourceProperty, source);
            group->setTitle(result);
        }
        return;
    }
    if (auto *combo = qobject_cast<QComboBox *>(widget)) {
        for (int i = 0; i < combo->count(); ++i) {
            const QString result = translated(combo->itemText(i));
            if (!result.isNull() && combo->itemText(i) != result)
                combo->setItemText(i, result);
        }
        return;
    }
    if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        for (int i = 0; i < tabs->count(); ++i) {
            const QString result = translated(tabs->tabText(i));
            if (!result.isNull() && tabs->tabText(i) != result)
                tabs->setTabText(i, result);
        }
        return;
    }
    if (auto *dock = qobject_cast<QDockWidget *>(widget)) {
        const QString source = dock->windowTitle().trimmed();
        const QString result = translated(source);
        if (!result.isNull() && dock->windowTitle() != result) {
            dock->setProperty(kSourceProperty, source);
            dock->setWindowTitle(result);
        }
        return;
    }
    if (auto *lineEdit = qobject_cast<QLineEdit *>(widget)) {
        const QString result = translated(lineEdit->placeholderText());
        if (!result.isNull() && lineEdit->placeholderText() != result)
            lineEdit->setPlaceholderText(result);
    }
}

QString originalTextAt(QWidget *widget, const QPoint &position) {
    if (!widget || !g_enabled)
        return {};

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
    else if (auto *combo = qobject_cast<QComboBox *>(widget))
        displayed = combo->currentText();
    else if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        const int tab = tabs->tabAt(position);
        if (tab >= 0)
            displayed = tabs->tabText(tab);
    }

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
    if (!widget || isInsideLayersPanel(widget))
        return {};

    if (auto *view = qobject_cast<QAbstractItemView *>(widget->parentWidget())) {
        if (widget == view->viewport()) {
            const QModelIndex index = view->indexAt(position);
            if (index.isValid())
                return index.data(Qt::DisplayRole).toString().trimmed();
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
    else if (auto *combo = qobject_cast<QComboBox *>(widget))
        displayed = combo->currentText();
    else if (auto *tabs = qobject_cast<QTabBar *>(widget)) {
        const int tab = tabs->tabAt(position);
        if (tab >= 0)
            displayed = tabs->tabText(tab);
    }

    displayed.remove(u'&');
    displayed = displayed.trimmed();
    const QString storedSource = widget->property(kSourceProperty).toString();
    if (!storedSource.isEmpty() && g_translations.value(storedSource) == displayed)
        return storedSource;
    const auto original = g_originals.constFind(displayed);
    return original == g_originals.cend() ? displayed : original.value();
}

bool saveTranslation(const QString &source, const QString &target, QString *error) {
    const QString translationPath = g_translationPaths.value(source);
    if (translationPath.isEmpty()) {
        if (error)
            *error = QStringLiteral("无法确定该词条所属的原始翻译文件。");
        return false;
    }

    QJsonObject root;
    QFile existing(translationPath);
    if (existing.exists() && existing.open(QIODevice::ReadOnly)) {
        QJsonParseError parseError;
        const QJsonDocument document =
            QJsonDocument::fromJson(existing.readAll(), &parseError);
        if (parseError.error == QJsonParseError::NoError && document.isObject())
            root = document.object();
        existing.close();
    }

    if (root.value(QStringLiteral("$schema")).toString() !=
        QStringLiteral("sp-translation-v1")) {
        if (error)
            *error = QStringLiteral("原始翻译文件格式无效：%1").arg(translationPath);
        return false;
    }
    QJsonObject translations = root.value(QStringLiteral("translations")).toObject();
    translations.insert(source, target);
    root.insert(QStringLiteral("translations"), translations);

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

void editTranslation(const QString &source, QWidget *parent) {
    if (source.isEmpty())
        return;
    const QString current = g_translations.value(source, source);

    QDialog dialog(parent);
    dialog.setWindowTitle(QStringLiteral("更改翻译"));
    dialog.setMinimumWidth(460);

    auto *layout = new QVBoxLayout(&dialog);
    auto *form = new QFormLayout();
    auto *sourceEdit = new QLineEdit(source, &dialog);
    auto *currentEdit = new QLineEdit(current, &dialog);
    auto *targetEdit = new QLineEdit(current, &dialog);
    sourceEdit->setReadOnly(true);
    currentEdit->setReadOnly(true);
    sourceEdit->setObjectName(QStringLiteral("sp_translation_source"));
    currentEdit->setObjectName(QStringLiteral("sp_translation_current"));
    targetEdit->setObjectName(QStringLiteral("sp_translation_target"));
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
    if (!saveTranslation(source, target, &error)) {
        QMessageBox::critical(parent, QStringLiteral("保存翻译失败"), error);
        return;
    }

    // Keep historical reverse entries until restart so widgets currently
    // showing an older translation can still resolve back to the source.
    g_translations.insert(source, target);
    g_originals.insert(target, source);
    refreshTranslatedViews();
}

class NativeUiFilter final : public QObject {
public:
    using QObject::QObject;
protected:
    bool eventFilter(QObject *object, QEvent *event) override {
        if (!g_enabled)
            return false;
        const auto type = event->type();
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
            QPointer<QWidget> safeWidget(widget);
            QTimer::singleShot(0, qApp, [source, safeWidget]() {
                if (safeWidget)
                    editTranslation(source, safeWidget.data());
            });
            event->accept();
            return true;
        }
        if (type == QEvent::ToolTip) {
            auto *widget = qobject_cast<QWidget *>(object);
            auto *help = static_cast<QHelpEvent *>(event);
            if (shouldSuppressTooltip(widget)) {
                QToolTip::hideText();
                event->accept();
                return true;
            }
            const QString source = originalTextAt(widget, help->pos());
            if (!source.isNull()) {
                QToolTip::showText(help->globalPos(), source, widget);
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
                    qobject_cast<QAbstractButton *>(widget))
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

NativeUiFilter *g_filter = nullptr;
QTimer *g_fallbackTimer = nullptr;

void scanVisibleWidgets() {
    if (!g_enabled)
        return;
    for (QWidget *widget : QApplication::allWidgets()) {
        if (widget && widget->isVisible())
            translateWidget(widget);
    }
}

void pinThisDll() {
    HMODULE module = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_PIN,
                       reinterpret_cast<LPCWSTR>(&pinThisDll), &module);
}
} // namespace

extern "C" __declspec(dllexport) int __cdecl sp_delegate_api_version() { return 5; }

extern "C" __declspec(dllexport) void __cdecl sp_delegate_set_translation_path(
    const wchar_t *source, const wchar_t *path) {
    if (!source || !path)
        return;
    g_translationPaths.insert(QString::fromWCharArray(source),
                              QString::fromWCharArray(path));
}

extern "C" __declspec(dllexport) void __cdecl sp_delegate_clear_translations() {
    g_translations.clear();
    g_originals.clear();
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

extern "C" __declspec(dllexport) int __cdecl sp_delegate_install(void *viewPointer) {
    pinThisDll();
    return installAssetDelegate(static_cast<QAbstractItemView *>(viewPointer));
}

extern "C" __declspec(dllexport) int __cdecl sp_delegate_install_ui(void *applicationPointer) {
    pinThisDll();
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
        g_filter = new NativeUiFilter(application);
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
