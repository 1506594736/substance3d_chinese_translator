#include <archive.h>
#include <archive_entry.h>
#include <hdf5.h>
#include <nlohmann/json.hpp>
#include <pugixml.hpp>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <optional>
#include <regex>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {
constexpr std::size_t kMaxArchiveMembers = 50000;
constexpr std::size_t kMaxNestedArchives = 128;
constexpr int kMaxNestedDepth = 3;

struct Request {
    fs::path source;
    fs::path output;
    std::string packageId = "extracted-assets";
    std::string description = "Extracted Substance asset labels";
    bool ordinaryFilenames = true;
    bool folderNames = false;
    std::set<std::string> attributes;
    std::unordered_set<std::string> excluded;
};

struct State {
    Request request;
    std::set<std::string> terms;
    json failures = json::array();
    std::size_t nestedArchives = 0;
    std::size_t processed = 0;
    std::size_t total = 0;
};

std::string pathUtf8(const fs::path &path) {
#ifdef _WIN32
    const std::wstring wide = path.native();
    if (wide.empty())
        return {};
    const int count = WideCharToMultiByte(CP_UTF8, 0, wide.data(),
                                          static_cast<int>(wide.size()), nullptr,
                                          0, nullptr, nullptr);
    std::string result(static_cast<std::size_t>(count), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()),
                        result.data(), count, nullptr, nullptr);
    return result;
#else
    return path.string();
#endif
}

fs::path pathFromUtf8(const std::string &value) {
#ifdef _WIN32
    if (value.empty())
        return {};
    const int count = MultiByteToWideChar(CP_UTF8, 0, value.data(),
                                          static_cast<int>(value.size()), nullptr,
                                          0);
    std::wstring result(static_cast<std::size_t>(count), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()),
                        result.data(), count);
    return fs::path(result);
#else
    return fs::path(value);
#endif
}

void emit(const json &message) {
    std::cout << message.dump() << '\n' << std::flush;
}

bool containsHan(const std::string &text) {
    // UTF-8 encodings of CJK Unified Ideographs begin in E3-E9. Decode only
    // enough to check the ranges used by the Python plug-in.
    std::size_t i = 0;
    while (i < text.size()) {
        const unsigned char first = static_cast<unsigned char>(text[i]);
        std::uint32_t codepoint = first;
        std::size_t length = 1;
        if ((first & 0xE0U) == 0xC0U) {
            codepoint = first & 0x1FU;
            length = 2;
        } else if ((first & 0xF0U) == 0xE0U) {
            codepoint = first & 0x0FU;
            length = 3;
        } else if ((first & 0xF8U) == 0xF0U) {
            codepoint = first & 0x07U;
            length = 4;
        }
        if (i + length > text.size())
            break;
        for (std::size_t j = 1; j < length; ++j)
            codepoint = (codepoint << 6U) |
                (static_cast<unsigned char>(text[i + j]) & 0x3FU);
        if (codepoint >= 0x3400U && codepoint <= 0x9FFFU)
            return true;
        i += length;
    }
    return false;
}

std::string trim(std::string value) {
    const auto space = [](unsigned char c) { return std::isspace(c) != 0; };
    value.erase(value.begin(),
                std::find_if(value.begin(), value.end(),
                             [&](char c) { return !space(static_cast<unsigned char>(c)); }));
    value.erase(std::find_if(value.rbegin(), value.rend(),
                             [&](char c) { return !space(static_cast<unsigned char>(c)); })
                    .base(),
                value.end());
    return value;
}

bool validSource(const std::string &source) {
    static const std::regex numeric(
        R"(^[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][+-]?\d+)?%?$)");
    const std::string value = trim(source);
    return !value.empty() && !containsHan(value) &&
           !std::regex_match(value, numeric);
}

void addTerm(State &state, const std::string &raw) {
    const std::string value = trim(raw);
    if (validSource(value) && state.request.excluded.count(value) == 0)
        state.terms.insert(value);
}

bool safeRelative(const fs::path &path) {
    if (path.empty() || path.is_absolute() || path.has_root_name())
        return false;
    for (const auto &part : path) {
        if (part == "..")
            return false;
    }
    return true;
}

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool looksLikeXml(const fs::path &path) {
    if (lower(path.extension().string()) == ".xml")
        return true;
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        return false;
    char buffer[4096]{};
    stream.read(buffer, sizeof(buffer));
    const std::string prefix(buffer, static_cast<std::size_t>(stream.gcount()));
    std::size_t position = 0;
    if (prefix.size() >= 3 &&
        static_cast<unsigned char>(prefix[0]) == 0xEFU &&
        static_cast<unsigned char>(prefix[1]) == 0xBBU &&
        static_cast<unsigned char>(prefix[2]) == 0xBFU)
        position = 3;
    while (position < prefix.size()) {
        const unsigned char c = static_cast<unsigned char>(prefix[position]);
        if (c != 0U && std::isspace(c) == 0)
            break;
        ++position;
    }
    return position != std::string::npos && prefix[position] == '<';
}

bool selectedAttribute(const State &state, const std::string &name) {
    if (state.request.attributes.count(name) != 0)
        return true;
    if (state.request.attributes.count("label") != 0) {
        static const std::regex labels(R"(^label\d*$)");
        return std::regex_match(name, labels);
    }
    return false;
}

void collectXmlNode(State &state, pugi::xml_node node) {
    if (node.type() == pugi::node_element) {
        for (pugi::xml_attribute attribute : node.attributes()) {
            const std::string name = attribute.name();
            if (!selectedAttribute(state, name))
                continue;
            const std::string value = trim(attribute.value());
            addTerm(state, value);
            const std::string nodeName = node.name();
            const bool groupPath = name == "group" ||
                (name == "label" && nodeName == "guigroup");
            if (!groupPath)
                continue;
            // Split only unspaced, non-numeric hierarchy slashes. Ratios such
            // as 7/1 and captions such as Leno / Gauze remain intact.
            std::size_t start = 0;
            bool split = false;
            while (start < value.size()) {
                std::size_t slash = value.find('/', start);
                if (slash == std::string::npos)
                    break;
                const unsigned char before = slash > 0
                    ? static_cast<unsigned char>(value[slash - 1]) : ' ';
                const unsigned char after = slash + 1 < value.size()
                    ? static_cast<unsigned char>(value[slash + 1]) : ' ';
                if (!std::isspace(before) && !std::isspace(after) &&
                    !std::isdigit(before) && !std::isdigit(after)) {
                    addTerm(state, value.substr(start, slash - start));
                    start = slash + 1;
                    split = true;
                } else {
                    start = slash + 1;
                }
            }
            if (split && start < value.size())
                addTerm(state, value.substr(start));
        }
    }
    for (pugi::xml_node child : node.children())
        collectXmlNode(state, child);
}

void parseXml(State &state, const fs::path &path) {
    pugi::xml_document document;
    const pugi::xml_parse_result loaded =
        document.load_file(path.c_str(), pugi::parse_default | pugi::parse_doctype);
    if (!loaded)
        throw std::runtime_error(std::string("XML parse error: ") + loaded.description());
    collectXmlNode(state, document);
}

void collectJsonMetadata(State &state, const json &value, int depth = 0) {
    if (depth > 64)
        return;
    if (value.is_object()) {
        for (const auto &[key, child] : value.items()) {
            const bool label = state.request.attributes.count("label") != 0 &&
                std::regex_match(key, std::regex(R"(^label\d*$)"));
            if (child.is_string() &&
                (label || state.request.attributes.count(key) != 0)) {
                addTerm(state, child.get<std::string>());
            } else if (key == "values" &&
                       state.request.attributes.count("values") != 0 &&
                       child.is_object()) {
                for (const auto &[caption, ignored] : child.items()) {
                    (void)ignored;
                    addTerm(state, caption);
                }
            } else {
                collectJsonMetadata(state, child, depth + 1);
            }
        }
    } else if (value.is_array()) {
        for (const auto &child : value)
            collectJsonMetadata(state, child, depth + 1);
    }
}

void parseGlsl(State &state, const fs::path &path) {
    std::ifstream stream(path, std::ios::binary);
    const std::string content((std::istreambuf_iterator<char>(stream)), {});
    // Painter annotations contain ordinary JSON objects embedded in comments.
    // Try every balanced object and retain those that parse successfully.
    for (std::size_t start = 0; start < content.size(); ++start) {
        if (content[start] != '{')
            continue;
        int depth = 0;
        bool quoted = false;
        bool escaped = false;
        for (std::size_t end = start; end < content.size(); ++end) {
            const char c = content[end];
            if (quoted) {
                if (escaped)
                    escaped = false;
                else if (c == '\\')
                    escaped = true;
                else if (c == '"')
                    quoted = false;
                continue;
            }
            if (c == '"')
                quoted = true;
            else if (c == '{')
                ++depth;
            else if (c == '}' && --depth == 0) {
                const json parsed = json::parse(
                    content.begin() + static_cast<std::ptrdiff_t>(start),
                    content.begin() + static_cast<std::ptrdiff_t>(end + 1),
                    nullptr, false);
                if (!parsed.is_discarded())
                    collectJsonMetadata(state, parsed);
                start = end;
                break;
            }
        }
    }
}

std::vector<std::string> lengthPrefixedStrings(const fs::path &path) {
    std::ifstream stream(path, std::ios::binary);
    const std::vector<unsigned char> data((std::istreambuf_iterator<char>(stream)), {});
    std::vector<std::string> result;
    for (std::size_t offset = 0; offset + 4 <= data.size();) {
        const std::uint32_t length = static_cast<std::uint32_t>(data[offset]) |
            (static_cast<std::uint32_t>(data[offset + 1]) << 8U) |
            (static_cast<std::uint32_t>(data[offset + 2]) << 16U) |
            (static_cast<std::uint32_t>(data[offset + 3]) << 24U);
        if (length > 0U && length < 500U && offset + 4U + length <= data.size()) {
            std::string value(reinterpret_cast<const char *>(data.data() + offset + 4U),
                              static_cast<std::size_t>(length));
            const bool printable = std::all_of(value.begin(), value.end(), [](unsigned char c) {
                return c >= 0x20U || c == '\t' || c == '\r' || c == '\n';
            });
            if (printable) {
                result.push_back(std::move(value));
                offset += 4U + length;
                continue;
            }
        }
        ++offset;
    }
    return result;
}

void parsePresetBin(State &state, const fs::path &path) {
    const std::vector<std::string> strings = lengthPrefixedStrings(path);
    std::unordered_set<std::string> fieldNames = {
        "label", "name", "displayname", "display_name", "layername", "layer_name"};
    for (std::size_t index = 0; index < strings.size(); ++index) {
        const std::string value = trim(strings[index]);
        const std::string folded = lower(value);
        if (fieldNames.count(folded) != 0 && index + 1 < strings.size()) {
            addTerm(state, strings[index + 1]);
            continue;
        }
        if (value.size() < 2U || value.size() > 80U ||
            value.rfind("Data", 0) == 0 || value.rfind("GUI", 0) == 0 ||
            value.find("://") != std::string::npos)
            continue;
        const bool hasSpace = value.find(' ') != std::string::npos;
        const bool titleWord = std::isupper(static_cast<unsigned char>(value.front())) != 0 &&
            std::all_of(value.begin() + 1, value.end(), [](unsigned char c) {
                return std::isalpha(c) != 0;
            });
        if (hasSpace || titleWord)
            addTerm(state, value);
    }
}

bool archiveFormat(const fs::path &path) {
    archive *reader = archive_read_new();
    archive_read_support_filter_all(reader);
    archive_read_support_format_all(reader);
    const int result = archive_read_open_filename_w(reader, path.c_str(), 10240);
    archive_read_free(reader);
    return result == ARCHIVE_OK;
}

void extractArchive(const fs::path &source, const fs::path &destination) {
    archive *reader = archive_read_new();
    archive_read_support_filter_all(reader);
    archive_read_support_format_all(reader);
    if (archive_read_open_filename_w(reader, source.c_str(), 10240) != ARCHIVE_OK) {
        const std::string message = archive_error_string(reader)
            ? archive_error_string(reader) : "unable to open archive";
        archive_read_free(reader);
        throw std::runtime_error(message);
    }
    std::size_t members = 0;
    archive_entry *entry = nullptr;
    while (archive_read_next_header(reader, &entry) == ARCHIVE_OK) {
        if (++members > kMaxArchiveMembers) {
            archive_read_free(reader);
            throw std::runtime_error("archive contains more than 50000 entries");
        }
        const wchar_t *wideName = archive_entry_pathname_w(entry);
        const char *utf8Name = archive_entry_pathname_utf8(entry);
        const fs::path relative = wideName ? fs::path(wideName)
            : pathFromUtf8(utf8Name ? utf8Name : "");
        if (!safeRelative(relative)) {
            archive_read_free(reader);
            throw std::runtime_error("unsafe archive path");
        }
        const auto type = archive_entry_filetype(entry);
        if (type == AE_IFLNK || type == AE_IFSOCK) {
            archive_read_free(reader);
            throw std::runtime_error("archive links are not allowed");
        }
        const fs::path output = destination / relative;
        if (type == AE_IFDIR) {
            fs::create_directories(output);
            continue;
        }
        fs::create_directories(output.parent_path());
        std::ofstream file(output, std::ios::binary | std::ios::trunc);
        if (!file) {
            archive_read_free(reader);
            throw std::runtime_error("cannot create extracted file");
        }
        const void *buffer = nullptr;
        std::size_t size = 0;
        la_int64_t offset = 0;
        while (true) {
            const int status = archive_read_data_block(reader, &buffer, &size, &offset);
            if (status == ARCHIVE_EOF)
                break;
            if (status != ARCHIVE_OK) {
                const std::string message = archive_error_string(reader)
                    ? archive_error_string(reader) : "archive read failed";
                archive_read_free(reader);
                throw std::runtime_error(message);
            }
            file.seekp(offset);
            file.write(static_cast<const char *>(buffer),
                       static_cast<std::streamsize>(size));
        }
    }
    archive_read_free(reader);
}

herr_t hdfVisitor(hid_t object, const char *name, const H5O_info2_t *info,
                  void *operatorData) {
    if (info->type != H5O_TYPE_DATASET)
        return 0;
    auto *context = static_cast<std::pair<fs::path, std::exception_ptr> *>(operatorData);
    try {
        const fs::path relative = pathFromUtf8(name);
        if (!safeRelative(relative))
            throw std::runtime_error("unsafe HDF5 dataset path");
        const hid_t dataset = H5Dopen2(object, name, H5P_DEFAULT);
        if (dataset < 0)
            throw std::runtime_error("cannot open HDF5 dataset");
        const hid_t type = H5Dget_type(dataset);
        const hid_t space = H5Dget_space(dataset);
        const hssize_t points = H5Sget_simple_extent_npoints(space);
        const std::size_t width = H5Tget_size(type);
        if (points < 0 || width == 0 ||
            static_cast<unsigned long long>(points) >
                (std::numeric_limits<std::size_t>::max)() / width) {
            H5Sclose(space); H5Tclose(type); H5Dclose(dataset);
            throw std::runtime_error("invalid HDF5 dataset size");
        }
        std::vector<unsigned char> data(static_cast<std::size_t>(points) * width);
        if (!data.empty() && H5Dread(dataset, type, H5S_ALL, H5S_ALL,
                                    H5P_DEFAULT, data.data()) < 0) {
            H5Sclose(space); H5Tclose(type); H5Dclose(dataset);
            throw std::runtime_error("cannot read HDF5 dataset");
        }
        H5Sclose(space); H5Tclose(type); H5Dclose(dataset);
        const fs::path output = context->first / relative;
        fs::create_directories(output.parent_path());
        std::ofstream file(output, std::ios::binary | std::ios::trunc);
        file.write(reinterpret_cast<const char *>(data.data()),
                   static_cast<std::streamsize>(data.size()));
    } catch (...) {
        context->second = std::current_exception();
        return -1;
    }
    return 0;
}

void extractHdf5(const fs::path &source, const fs::path &destination) {
    const hid_t file = H5Fopen(pathUtf8(source).c_str(), H5F_ACC_RDONLY, H5P_DEFAULT);
    if (file < 0)
        throw std::runtime_error("cannot open HDF5 container");
    std::pair<fs::path, std::exception_ptr> context{destination, nullptr};
    const herr_t result = H5Ovisit3(file, H5_INDEX_NAME, H5_ITER_NATIVE,
                                    hdfVisitor, &context, H5O_INFO_BASIC);
    H5Fclose(file);
    if (context.second)
        std::rethrow_exception(context.second);
    if (result < 0)
        throw std::runtime_error("HDF5 traversal failed");
}

bool isHdf5(const fs::path &path) {
    return H5Fis_hdf5(pathUtf8(path).c_str()) > 0;
}

bool isContainer(const fs::path &path) {
    try {
        return isHdf5(path) || archiveFormat(path);
    } catch (...) {
        return false;
    }
}

void extractContainer(const fs::path &source, const fs::path &destination) {
    fs::create_directories(destination);
    if (isHdf5(source))
        extractHdf5(source, destination);
    else
        extractArchive(source, destination);
}

void scanExtracted(State &state, const fs::path &root, int depth) {
    std::vector<fs::path> files;
    for (const auto &entry : fs::recursive_directory_iterator(root)) {
        if (entry.is_regular_file())
            files.push_back(entry.path());
    }
    for (const fs::path &path : files) {
        const std::string extension = lower(path.extension().string());
        if (looksLikeXml(path)) {
            try {
                parseXml(state, path);
            } catch (const std::exception &error) {
                state.failures.push_back({{"file", pathUtf8(path)},
                                          {"message", error.what()}});
            }
        }
        if (lower(path.filename().string()) == "preset.bin") {
            try {
                parsePresetBin(state, path);
            } catch (const std::exception &error) {
                state.failures.push_back({{"file", pathUtf8(path)},
                                          {"message", error.what()}});
            }
        }
        if (depth >= kMaxNestedDepth || !isContainer(path))
            continue;
        if (state.nestedArchives >= kMaxNestedArchives)
            throw std::runtime_error("more than 128 nested containers");
        const fs::path destination = root /
            ("_nested_" + std::to_string(++state.nestedArchives));
        try {
            extractContainer(path, destination);
            scanExtracted(state, destination, depth + 1);
        } catch (const std::exception &error) {
            state.failures.push_back({{"file", pathUtf8(path)},
                                      {"message", error.what()}});
        }
    }
}

void processAsset(State &state, const fs::path &asset) {
    static const std::set<std::string> knownContainers = {
        ".sbsar", ".spsm", ".sppr", ".spp", ".sbsprs", ".sbsasm",
        ".zip", ".7z"};
    static const std::set<std::string> glsl = {
        ".glsl", ".glslfx", ".vert", ".frag", ".geom", ".tesc",
        ".tese", ".comp"};
    const std::string extension = lower(asset.extension().string());
    const bool container = isContainer(asset);
    if (container || knownContainers.count(extension) != 0 ||
        state.request.ordinaryFilenames)
        addTerm(state, pathUtf8(asset.stem()));
    if (container) {
        const fs::path temporary = fs::temp_directory_path() /
            ("sp_translation_extract_" +
             std::to_string(std::chrono::high_resolution_clock::now()
                                .time_since_epoch().count()));
        try {
            extractContainer(asset, temporary);
            scanExtracted(state, temporary, 1);
            fs::remove_all(temporary);
        } catch (...) {
            std::error_code ignored;
            fs::remove_all(temporary, ignored);
            throw;
        }
    } else if (glsl.count(extension) != 0) {
        parseGlsl(state, asset);
    } else if (looksLikeXml(asset)) {
        parseXml(state, asset);
    }
}

Request loadRequest(const fs::path &path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        throw std::runtime_error("cannot open request JSON");
    const json payload = json::parse(stream);
    Request request;
    request.source = pathFromUtf8(payload.at("source").get<std::string>());
    request.output = pathFromUtf8(payload.at("output").get<std::string>());
    request.packageId = payload.value("package_id", request.packageId);
    request.description = payload.value("description", request.description);
    request.ordinaryFilenames = payload.value("ordinary_filenames", true);
    request.folderNames = payload.value("folder_names", false);
    for (const auto &attribute : payload.value("attributes", json::array()))
        request.attributes.insert(attribute.get<std::string>());
    for (const auto &source : payload.value("excluded", json::array()))
        request.excluded.insert(source.get<std::string>());
    return request;
}

json loadExisting(const fs::path &path) {
    if (!fs::is_regular_file(path))
        return json::object();
    try {
        std::ifstream stream(path, std::ios::binary);
        const json payload = json::parse(stream);
        if (payload.value("$schema", "") == "sp-translation-v1" &&
            payload.contains("translations") &&
            payload["translations"].is_object())
            return payload["translations"];
    } catch (...) {
    }
    return json::object();
}

void writeResult(const State &state) {
    json translations = loadExisting(state.request.output);
    for (const std::string &term : state.terms) {
        if (!translations.contains(term))
            translations[term] = "";
    }
    json sorted = json::object();
    std::vector<std::string> keys;
    for (const auto &[key, value] : translations.items()) {
        if (value.is_string() && validSource(key))
            keys.push_back(key);
    }
    std::sort(keys.begin(), keys.end(), [](const std::string &a,
                                           const std::string &b) {
        return lower(a) < lower(b);
    });
    for (const std::string &key : keys)
        sorted[key] = translations[key];
    const json payload = {
        {"$schema", "sp-translation-v1"},
        {"id", state.request.packageId},
        {"language", "zh-CN"},
        {"description", state.request.description},
        {"extraction", {{"asset_count", state.total},
                        {"failed_count", state.failures.size()},
                        {"term_count", sorted.size()},
                        {"attributes", state.request.attributes},
                        {"ordinary_filenames", state.request.ordinaryFilenames},
                        {"container_filenames", true},
                        {"folder_names", state.request.folderNames},
                        {"glsl_metadata", true}}},
        {"translations", sorted}};
    fs::create_directories(state.request.output.parent_path());
    const fs::path temporary = state.request.output.parent_path() /
        (state.request.output.filename().wstring() + L".tmp");
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        stream << payload.dump(2) << '\n';
        if (!stream)
            throw std::runtime_error("failed to write output JSON");
    }
#ifdef _WIN32
    if (!MoveFileExW(temporary.c_str(), state.request.output.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("failed to replace output JSON");
#else
    fs::rename(temporary, state.request.output);
#endif

    fs::path failureLog = state.request.output;
    failureLog.replace_filename(state.request.output.stem().wstring() +
                                L"_failures.txt");
    if (state.failures.empty()) {
        std::error_code ignored;
        fs::remove(failureLog, ignored);
    } else {
        std::ofstream failures(failureLog, std::ios::binary | std::ios::trunc);
        for (const auto &failure : state.failures)
            failures << failure.value("file", "") << '\t'
                     << failure.value("message", "") << '\n';
    }
}

int run(const fs::path &requestPath) {
    State state{loadRequest(requestPath)};
    if (!fs::is_directory(state.request.source))
        throw std::runtime_error("source directory does not exist");
    std::vector<fs::path> assets;
    auto iterator = fs::recursive_directory_iterator(
        state.request.source, fs::directory_options::skip_permission_denied);
    for (const auto &entry : iterator) {
        if (entry.is_directory()) {
            const std::string name = lower(entry.path().filename().string());
            if (name == "__pycache__" || name == "_unpacked_assets" ||
                name == ".alg_meta") {
                iterator.disable_recursion_pending();
                continue;
            }
            if (state.request.folderNames)
                addTerm(state, pathUtf8(entry.path().filename()));
        } else if (entry.is_regular_file() &&
                   fs::absolute(entry.path()) != fs::absolute(state.request.output)) {
            assets.push_back(entry.path());
        }
    }
    std::sort(assets.begin(), assets.end());
    state.total = assets.size();
    for (const fs::path &asset : assets) {
        ++state.processed;
        emit({{"type", "progress"}, {"current", state.processed},
              {"total", state.total}, {"file", pathUtf8(asset)}});
        try {
            processAsset(state, asset);
        } catch (const std::exception &error) {
            state.failures.push_back({{"file", pathUtf8(asset)},
                                      {"message", error.what()}});
            emit({{"type", "warning"}, {"file", pathUtf8(asset)},
                  {"message", error.what()}});
        }
    }
    writeResult(state);
    emit({{"type", "finished"}, {"terms", state.terms.size()},
          {"failures", state.failures.size()},
          {"output", pathUtf8(state.request.output)}});
    return 0;
}
} // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) {
#else
int main(int argc, char **argv) {
#endif
    try {
        if (argc != 3 || std::wstring(argv[1]) != L"--request") {
            std::cerr << "usage: sp_translation_extractor --request request.json\n";
            return 2;
        }
#ifdef _WIN32
        return run(fs::path(argv[2]));
#else
        return run(fs::path(argv[2]));
#endif
    } catch (const std::exception &error) {
        emit({{"type", "fatal"}, {"message", error.what()}});
        return 1;
    }
}
