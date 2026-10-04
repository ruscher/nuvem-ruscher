# Funções comuns dos comandos falsos usados no modo simulado do helper.
# shellcheck shell=bash
sim_log() {
    printf '%s %s\n' "${0##*/}" "$*" >>"${NUVEM_RUSCHER_SIM_ROOT}/calls.log"
}
sim_state() {
    local file="${NUVEM_RUSCHER_SIM_ROOT}/state/$1"
    if [[ $# -ge 2 ]]; then
        mkdir -p "${file%/*}"
        printf '%s' "$2" >"$file"
    elif [[ -f $file ]]; then
        cat "$file"
    fi
}
