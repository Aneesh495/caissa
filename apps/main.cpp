#include "caissa/version.hpp"
#include <iostream>
#include <string_view>
int main(int argc, char** argv) {
    if (argc == 2 && std::string_view(argv[1]) == "--version") {
        std::cout << caissa::version() << '\n';
        return 0;
    }
    std::cerr << "No engine interface available in this foundational increment\n";
    return 2;
}
