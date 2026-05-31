#include "parser/compile_db.hpp"

#include <clang-c/CXCompilationDatabase.h>

#include "parser/cursor_utils.hpp"

namespace clangquill::parser {

CompileDb::~CompileDb() {
  if (db_) {
    clang_CompilationDatabase_dispose(
        static_cast<CXCompilationDatabase>(db_));
  }
}

bool CompileDb::load(const std::string& dir) {
  CXCompilationDatabase_Error err = CXCompilationDatabase_NoError;
  CXCompilationDatabase db =
      clang_CompilationDatabase_fromDirectory(dir.c_str(), &err);
  if (err != CXCompilationDatabase_NoError) {
    if (db) clang_CompilationDatabase_dispose(db);
    return false;
  }
  db_ = db;
  return true;
}

std::vector<std::string> CompileDb::args_for(const std::string& path) const {
  std::vector<std::string> args;
  if (!db_) return args;

  CXCompileCommands cmds = clang_CompilationDatabase_getCompileCommands(
      static_cast<CXCompilationDatabase>(db_), path.c_str());
  if (!cmds) return args;

  unsigned n = clang_CompileCommands_getSize(cmds);
  if (n > 0) {
    CXCompileCommand cmd = clang_CompileCommands_getCommand(cmds, 0);
    unsigned argc = clang_CompileCommand_getNumArgs(cmd);
    // Skip argv[0] (the compiler) and drop any bare token equal to the source
    // path; libclang adds the file back itself.
    for (unsigned i = 1; i < argc; ++i) {
      std::string a = to_string(clang_CompileCommand_getArg(cmd, i));
      if (a == path) continue;
      args.push_back(std::move(a));
    }
  }
  clang_CompileCommands_dispose(cmds);
  return args;
}

}  // namespace clangquill::parser
