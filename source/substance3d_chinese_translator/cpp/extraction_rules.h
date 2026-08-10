#pragma once

// 词条可提取判定规则（唯一实现）：
// 提取器（extractor.cpp）与翻译引擎（translation_ui_delegate.cpp）共用，
// Python 端不再重复实现，只调用翻译引擎导出的判定函数。

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <regex>
#include <string>

namespace extraction_rules {

inline bool containsHan(const std::string &text) {
    // UTF-8 encodings of CJK Unified Ideographs begin in E3-E9. Decode only
    // enough to check the ranges used by the plug-in.
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

inline std::string trim(std::string value) {
    const auto space = [](unsigned char c) { return std::isspace(c) != 0; };
    value.erase(value.begin(),
                std::find_if(value.begin(), value.end(),
                             [&](char c) {
                                 return !space(static_cast<unsigned char>(c));
                             }));
    value.erase(std::find_if(value.rbegin(), value.rend(),
                             [&](char c) {
                                 return !space(static_cast<unsigned char>(c));
                             })
                    .base(),
                value.end());
    return value;
}

inline bool looksLikeAssetUrl(const std::string &value) {
    return value.find("?version=") != std::string::npos ||
           (!value.empty() && value.front() == '/' &&
            value.find('?') != std::string::npos);
}

inline bool validSource(const std::string &source) {
    static const std::regex numeric(
        R"(^[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][+-]?\d+)?%?$)");
    const std::string value = trim(source);
    return !value.empty() && !containsHan(value) &&
           !looksLikeAssetUrl(value) &&
           !std::regex_match(value, numeric);
}

}  // namespace extraction_rules
