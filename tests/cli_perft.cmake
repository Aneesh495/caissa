set(start_fen "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

function(expect_invalid_variant mode)
  execute_process(COMMAND "${CAISSA}" "${mode}" 1 "${start_fen}" ${ARGN}
    RESULT_VARIABLE result ERROR_VARIABLE error)
  if(NOT result STREQUAL "1" OR NOT error MATCHES "Chess960 marker")
    message(FATAL_ERROR "${mode} accepted unexpected variant arguments: ${ARGN}")
  endif()
endfunction()

foreach(mode IN ITEMS --perft --divide)
  expect_invalid_variant("${mode}" invalid-variant)
  expect_invalid_variant("${mode}" 960 unexpected)
endforeach()

execute_process(COMMAND "${CAISSA}" --perft 1 "${start_fen}" 960
  RESULT_VARIABLE result OUTPUT_VARIABLE output OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT result STREQUAL "0" OR NOT output STREQUAL "20")
  message(FATAL_ERROR "Expected Chess960 perft to return 20, got ${result}: ${output}")
endif()
