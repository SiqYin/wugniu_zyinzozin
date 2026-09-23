/*
 * Convert the JavaScript database objects embedded in index.html into
 * separate SQLite database files under data/.
 *
 * Build (when the SQLite development package is installed):
 *   cc -O2 -std=c11 -Wall -Wextra -pedantic get_data.c -lsqlite3 -o get_data
 *
 * Run:
 *   ./get_data                 # reads index1.html, writes data/
 *   ./get_data FILE OUT_DIR    # custom input and output directory
 *
 * The converter reads only these constants from index.html:
 *   DB_suhu, DB_qingmo, DB_shanghai, DB_suzhou, DB_pingtan, S2T
 * T2S is intentionally ignored because conversion is simplified -> traditional only.
 */

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifdef _WIN32
#include <direct.h>
#define make_dir(path) _mkdir(path)
#define PATH_SEPARATOR '\\'
#else
#include <unistd.h>
#define make_dir(path) mkdir((path), 0777)
#define PATH_SEPARATOR '/'
#endif

/*
 * Prefer the official header.  The small fallback declaration block lets this
 * source compile in minimal environments that have the SQLite runtime library
 * but not sqlite3.h.  It declares only the stable API used below.
 */
#if defined(__has_include)
#  if __has_include(<sqlite3.h>)
#    include <sqlite3.h>
#    define HAVE_SQLITE3_HEADER 1
#  endif
#endif

#ifndef HAVE_SQLITE3_HEADER
typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
typedef long long sqlite3_int64;
typedef void (*sqlite3_destructor_type)(void *);

extern int sqlite3_open(const char *, sqlite3 **);
extern int sqlite3_close(sqlite3 *);
extern const char *sqlite3_errmsg(sqlite3 *);
extern int sqlite3_exec(sqlite3 *, const char *,
                        int (*)(void *, int, char **, char **), void *, char **);
extern void sqlite3_free(void *);
extern int sqlite3_prepare_v2(sqlite3 *, const char *, int, sqlite3_stmt **,
                              const char **);
extern int sqlite3_bind_text(sqlite3_stmt *, int, const char *, int,
                             sqlite3_destructor_type);
extern int sqlite3_step(sqlite3_stmt *);
extern int sqlite3_finalize(sqlite3_stmt *);
extern sqlite3_int64 sqlite3_column_int64(sqlite3_stmt *, int);
extern sqlite3_int64 sqlite3_changes64(sqlite3 *);
extern const char *sqlite3_libversion(void);

#define SQLITE_OK 0
#define SQLITE_ROW 100
#define SQLITE_DONE 101
#define SQLITE_TRANSIENT ((sqlite3_destructor_type)-1)
#endif

struct source_spec {
    const char *constant_name;
    const char *file_name;
    const char *code;
    const char *display_name;
    int has_romanization;
};

static const struct source_spec READING_SOURCES[] = {
    {"DB_suhu",     "DB_suhu.sqlite3",     "suhu",     "蘇滬混合腔", 1},
    {"DB_qingmo",   "DB_qingmo.sqlite3",   "qingmo",   "清末蘇州話", 0},
    {"DB_shanghai", "DB_shanghai.sqlite3", "shanghai", "上海話",     0},
    {"DB_suzhou",   "DB_suzhou.sqlite3",   "suzhou",   "蘇州話",     0},
    {"DB_pingtan",  "DB_pingtan.sqlite3",  "pingtan",  "蘇州評彈音", 0}
};

static void die_message(const char *message)
{
    fprintf(stderr, "get_data: %s\n", message);
    exit(EXIT_FAILURE);
}

static void *xmalloc(size_t size)
{
    void *ptr = malloc(size ? size : 1);
    if (!ptr)
        die_message("out of memory");
    return ptr;
}

static char *read_entire_file(const char *path, size_t *length_out)
{
    FILE *file;
    long length;
    size_t got;
    char *buffer;

    file = fopen(path, "rb");
    if (!file) {
        fprintf(stderr, "get_data: cannot open %s: %s\n", path, strerror(errno));
        return NULL;
    }
    if (fseek(file, 0, SEEK_END) != 0 || (length = ftell(file)) < 0 ||
        fseek(file, 0, SEEK_SET) != 0) {
        fprintf(stderr, "get_data: cannot determine size of %s\n", path);
        fclose(file);
        return NULL;
    }

    buffer = (char *)xmalloc((size_t)length + 1);
    got = fread(buffer, 1, (size_t)length, file);
    if (got != (size_t)length) {
        fprintf(stderr, "get_data: cannot read all of %s\n", path);
        free(buffer);
        fclose(file);
        return NULL;
    }
    buffer[got] = '\0';
    fclose(file);
    *length_out = got;
    return buffer;
}

/*
 * Return a newly allocated copy of the JSON object assigned to a top-level
 * `const NAME = {...};` declaration.  Braces inside JSON strings are ignored.
 */
static char *extract_json_object(const char *html, size_t html_length,
                                 const char *constant_name, size_t *json_length)
{
    char marker[128];
    const char *found;
    const char *start;
    const char *cursor;
    const char *end = html + html_length;
    int depth = 0;
    int in_string = 0;
    int escaped = 0;
    size_t length;
    char *json;

    if (snprintf(marker, sizeof(marker), "const %s", constant_name) < 0 ||
        strlen(marker) >= sizeof(marker)) {
        fprintf(stderr, "get_data: constant name is too long: %s\n", constant_name);
        return NULL;
    }

    found = strstr(html, marker);
    if (!found) {
        fprintf(stderr, "get_data: %s was not found in index.html\n", constant_name);
        return NULL;
    }
    cursor = found + strlen(marker);
    while (cursor < end && (*cursor == ' ' || *cursor == '\t' ||
                            *cursor == '\r' || *cursor == '\n'))
        ++cursor;
    if (cursor >= end || *cursor != '=') {
        fprintf(stderr, "get_data: expected '=' after %s\n", constant_name);
        return NULL;
    }
    ++cursor;
    while (cursor < end && (*cursor == ' ' || *cursor == '\t' ||
                            *cursor == '\r' || *cursor == '\n'))
        ++cursor;
    if (cursor >= end || *cursor != '{') {
        fprintf(stderr, "get_data: expected JSON object after %s\n", constant_name);
        return NULL;
    }

    start = cursor;
    for (; cursor < end; ++cursor) {
        unsigned char ch = (unsigned char)*cursor;

        if (in_string) {
            if (escaped) {
                escaped = 0;
            } else if (ch == '\\') {
                escaped = 1;
            } else if (ch == '"') {
                in_string = 0;
            }
            continue;
        }

        if (ch == '"') {
            in_string = 1;
        } else if (ch == '{') {
            ++depth;
        } else if (ch == '}') {
            --depth;
            if (depth == 0) {
                length = (size_t)(cursor - start + 1);
                json = (char *)xmalloc(length + 1);
                memcpy(json, start, length);
                json[length] = '\0';
                *json_length = length;
                return json;
            }
            if (depth < 0)
                break;
        }
    }

    fprintf(stderr, "get_data: unterminated JSON object for %s\n", constant_name);
    return NULL;
}

static int ensure_output_directory(const char *path)
{
    struct stat info;

    if (stat(path, &info) == 0) {
        if (S_ISDIR(info.st_mode))
            return 0;
        fprintf(stderr, "get_data: %s exists but is not a directory\n", path);
        return -1;
    }
    if (errno != ENOENT) {
        fprintf(stderr, "get_data: cannot inspect %s: %s\n", path, strerror(errno));
        return -1;
    }
    if (make_dir(path) != 0) {
        fprintf(stderr, "get_data: cannot create %s: %s\n", path, strerror(errno));
        return -1;
    }
    return 0;
}

static char *join_path(const char *directory, const char *name)
{
    size_t dlen = strlen(directory);
    size_t nlen = strlen(name);
    int needs_separator = dlen > 0 && directory[dlen - 1] != '/' &&
                          directory[dlen - 1] != '\\';
    char *path = (char *)xmalloc(dlen + (size_t)needs_separator + nlen + 1);

    memcpy(path, directory, dlen);
    if (needs_separator)
        path[dlen++] = PATH_SEPARATOR;
    memcpy(path + dlen, name, nlen + 1);
    return path;
}

static char *temporary_path(const char *final_path)
{
    static const char suffix[] = ".tmp";
    size_t length = strlen(final_path);
    char *path = (char *)xmalloc(length + sizeof(suffix));

    memcpy(path, final_path, length);
    memcpy(path + length, suffix, sizeof(suffix));
    return path;
}

static int exec_sql(sqlite3 *db, const char *sql)
{
    char *error = NULL;
    int rc = sqlite3_exec(db, sql, NULL, NULL, &error);

    if (rc != SQLITE_OK) {
        fprintf(stderr, "get_data: SQLite error: %s\n",
                error ? error : sqlite3_errmsg(db));
        sqlite3_free(error);
        return -1;
    }
    return 0;
}

static int bind_json(sqlite3 *db, sqlite3_stmt *statement,
                     const char *json, size_t json_length)
{
    if (json_length > (size_t)INT_MAX) {
        fprintf(stderr, "get_data: JSON object is too large for SQLite binding\n");
        return -1;
    }
    if (sqlite3_bind_text(statement, 1, json, (int)json_length,
                          SQLITE_TRANSIENT) != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot bind JSON: %s\n", sqlite3_errmsg(db));
        return -1;
    }
    return 0;
}

static int json_is_valid(sqlite3 *db, const char *json, size_t json_length)
{
    sqlite3_stmt *statement = NULL;
    int rc;
    int valid = 0;

    rc = sqlite3_prepare_v2(db, "SELECT json_valid(?1)", -1, &statement, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr,
                "get_data: this SQLite build does not provide the JSON functions: %s\n",
                sqlite3_errmsg(db));
        return 0;
    }
    if (bind_json(db, statement, json, json_length) == 0 &&
        sqlite3_step(statement) == SQLITE_ROW)
        valid = sqlite3_column_int64(statement, 0) == 1;
    sqlite3_finalize(statement);
    return valid;
}

static sqlite3_int64 table_count(sqlite3 *db, const char *table_name)
{
    char sql[128];
    sqlite3_stmt *statement = NULL;
    sqlite3_int64 count = -1;

    if (snprintf(sql, sizeof(sql), "SELECT count(*) FROM %s", table_name) < 0 ||
        strlen(sql) >= sizeof(sql))
        return -1;
    if (sqlite3_prepare_v2(db, sql, -1, &statement, NULL) != SQLITE_OK)
        return -1;
    if (sqlite3_step(statement) == SQLITE_ROW)
        count = sqlite3_column_int64(statement, 0);
    sqlite3_finalize(statement);
    return count;
}

static int install_database(const char *temporary, const char *final_path)
{
#ifdef _WIN32
    if (remove(final_path) != 0 && errno != ENOENT) {
        fprintf(stderr, "get_data: cannot replace %s: %s\n",
                final_path, strerror(errno));
        return -1;
    }
#endif
    if (rename(temporary, final_path) != 0) {
        fprintf(stderr, "get_data: cannot move %s to %s: %s\n",
                temporary, final_path, strerror(errno));
        return -1;
    }
    return 0;
}

static int write_readings_database(const char *output_directory,
                                   const struct source_spec *spec,
                                   const char *json, size_t json_length)
{
    static const char schema_sql[] =
        "PRAGMA journal_mode=DELETE;"
        "PRAGMA synchronous=FULL;"
        "PRAGMA user_version=1;"
        "CREATE TABLE metadata ("
        "  code TEXT NOT NULL,"
        "  display_name TEXT NOT NULL,"
        "  source_constant TEXT NOT NULL,"
        "  ipa INTEGER NOT NULL CHECK (ipa IN (0,1)),"
        "  romanization INTEGER NOT NULL CHECK (romanization IN (0,1))"
        ");"
        "CREATE TABLE readings ("
        "  id INTEGER PRIMARY KEY,"
        "  character TEXT NOT NULL,"
        "  romanization TEXT,"
        "  ipa TEXT,"
        "  audio TEXT DEFAULT NULL,"
        "  note TEXT"
        ");";
    static const char insert_suhu_sql[] =
        "INSERT INTO readings(character, romanization, ipa, audio, note) "
        "SELECT root.key, "
        "       json_extract(item.value, '$[0]'), "
        "       json_extract(item.value, '$[1]'), "
        "       NULL, "
        "       json_extract(item.value, '$[2]') "
        "FROM json_each(?1) AS root, json_each(root.value) AS item";
    static const char insert_ipa_sql[] =
        "INSERT INTO readings(character, romanization, ipa, audio, note) "
        "SELECT root.key, "
        "       NULL, "
        "       json_extract(item.value, '$[0]'), "
        "       NULL, "
        "       json_extract(item.value, '$[1]') "
        "FROM json_each(?1) AS root, json_each(root.value) AS item";
    char *final_path = join_path(output_directory, spec->file_name);
    char *temp_path = temporary_path(final_path);
    sqlite3 *db = NULL;
    sqlite3_stmt *statement = NULL;
    sqlite3_stmt *metadata = NULL;
    sqlite3_int64 count;
    int rc;
    int ok = -1;

    remove(temp_path);
    rc = sqlite3_open(temp_path, &db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot create %s: %s\n",
                temp_path, db ? sqlite3_errmsg(db) : "unknown SQLite error");
        goto cleanup;
    }
    if (!json_is_valid(db, json, json_length)) {
        fprintf(stderr, "get_data: %s is not valid JSON\n", spec->constant_name);
        goto cleanup;
    }
    if (exec_sql(db, schema_sql) != 0 || exec_sql(db, "BEGIN IMMEDIATE") != 0)
        goto cleanup;

    rc = sqlite3_prepare_v2(
        db,
        "INSERT INTO metadata(code, display_name, source_constant, ipa, romanization) "
        "VALUES (?1, ?2, ?3, 1, ?4)",
        -1, &metadata, NULL);
    if (rc != SQLITE_OK ||
        sqlite3_bind_text(metadata, 1, spec->code, -1, SQLITE_TRANSIENT) != SQLITE_OK ||
        sqlite3_bind_text(metadata, 2, spec->display_name, -1, SQLITE_TRANSIENT) != SQLITE_OK ||
        sqlite3_bind_text(metadata, 3, spec->constant_name, -1, SQLITE_TRANSIENT) != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot prepare metadata for %s: %s\n",
                spec->constant_name, sqlite3_errmsg(db));
        goto rollback;
    }
    {
        char bool_text[2];
        bool_text[0] = spec->has_romanization ? '1' : '0';
        bool_text[1] = '\0';
        if (sqlite3_bind_text(metadata, 4, bool_text, 1, SQLITE_TRANSIENT) != SQLITE_OK ||
            sqlite3_step(metadata) != SQLITE_DONE) {
            fprintf(stderr, "get_data: cannot write metadata for %s: %s\n",
                    spec->constant_name, sqlite3_errmsg(db));
            goto rollback;
        }
    }
    sqlite3_finalize(metadata);
    metadata = NULL;

    rc = sqlite3_prepare_v2(db,
                            spec->has_romanization ? insert_suhu_sql : insert_ipa_sql,
                            -1, &statement, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot prepare import for %s: %s\n",
                spec->constant_name, sqlite3_errmsg(db));
        goto rollback;
    }
    if (bind_json(db, statement, json, json_length) != 0)
        goto rollback;
    rc = sqlite3_step(statement);
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "get_data: cannot import %s: %s\n",
                spec->constant_name, sqlite3_errmsg(db));
        goto rollback;
    }
    sqlite3_finalize(statement);
    statement = NULL;

    if (exec_sql(db,
                 "CREATE INDEX idx_readings_character ON readings(character);"
                 "CREATE INDEX idx_readings_romanization ON readings(romanization);"
                 "COMMIT;"
                 "VACUUM;") != 0)
        goto cleanup;

    count = table_count(db, "readings");
    if (count < 0) {
        fprintf(stderr, "get_data: cannot count rows in %s\n", temp_path);
        goto cleanup;
    }
    if (sqlite3_close(db) != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot close %s\n", temp_path);
        db = NULL;
        goto cleanup;
    }
    db = NULL;
    if (install_database(temp_path, final_path) != 0)
        goto cleanup;

    printf("%-12s -> %s (%lld readings)\n",
           spec->constant_name, final_path, (long long)count);
    ok = 0;
    goto cleanup;

rollback:
    exec_sql(db, "ROLLBACK");
cleanup:
    if (statement)
        sqlite3_finalize(statement);
    if (metadata)
        sqlite3_finalize(metadata);
    if (db)
        sqlite3_close(db);
    if (ok != 0)
        remove(temp_path);
    free(temp_path);
    free(final_path);
    return ok;
}

static int write_s2t_database(const char *output_directory,
                              const char *json, size_t json_length)
{
    static const char schema_sql[] =
        "PRAGMA journal_mode=DELETE;"
        "PRAGMA synchronous=FULL;"
        "PRAGMA user_version=1;"
        "CREATE TABLE character_variants ("
        "  id INTEGER PRIMARY KEY,"
        "  source_character TEXT NOT NULL,"
        "  target_character TEXT NOT NULL,"
        "  variant_type TEXT NOT NULL DEFAULT 's2t' "
        "    CHECK (variant_type = 's2t')"
        ");";
    static const char insert_sql[] =
        "INSERT INTO character_variants(source_character, target_character, variant_type) "
        "SELECT root.key, item.value, 's2t' "
        "FROM json_each(?1) AS root, json_each(root.value) AS item";
    char *final_path = join_path(output_directory, "S2T.sqlite3");
    char *temp_path = temporary_path(final_path);
    sqlite3 *db = NULL;
    sqlite3_stmt *statement = NULL;
    sqlite3_int64 count;
    int rc;
    int ok = -1;

    remove(temp_path);
    rc = sqlite3_open(temp_path, &db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot create %s: %s\n",
                temp_path, db ? sqlite3_errmsg(db) : "unknown SQLite error");
        goto cleanup;
    }
    if (!json_is_valid(db, json, json_length)) {
        fprintf(stderr, "get_data: S2T is not valid JSON\n");
        goto cleanup;
    }
    if (exec_sql(db, schema_sql) != 0 || exec_sql(db, "BEGIN IMMEDIATE") != 0)
        goto cleanup;

    rc = sqlite3_prepare_v2(db, insert_sql, -1, &statement, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot prepare S2T import: %s\n", sqlite3_errmsg(db));
        goto rollback;
    }
    if (bind_json(db, statement, json, json_length) != 0)
        goto rollback;
    rc = sqlite3_step(statement);
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "get_data: cannot import S2T: %s\n", sqlite3_errmsg(db));
        goto rollback;
    }
    sqlite3_finalize(statement);
    statement = NULL;

    if (exec_sql(db,
                 "CREATE INDEX idx_character_variants_source "
                 "ON character_variants(source_character);"
                 "COMMIT;"
                 "VACUUM;") != 0)
        goto cleanup;

    count = table_count(db, "character_variants");
    if (count < 0) {
        fprintf(stderr, "get_data: cannot count rows in %s\n", temp_path);
        goto cleanup;
    }
    if (sqlite3_close(db) != SQLITE_OK) {
        fprintf(stderr, "get_data: cannot close %s\n", temp_path);
        db = NULL;
        goto cleanup;
    }
    db = NULL;
    if (install_database(temp_path, final_path) != 0)
        goto cleanup;

    printf("%-12s -> %s (%lld mappings)\n", "S2T", final_path,
           (long long)count);
    ok = 0;
    goto cleanup;

rollback:
    exec_sql(db, "ROLLBACK");
cleanup:
    if (statement)
        sqlite3_finalize(statement);
    if (db)
        sqlite3_close(db);
    if (ok != 0)
        remove(temp_path);
    free(temp_path);
    free(final_path);
    return ok;
}

int main(int argc, char **argv)
{
    const char *input_path = "index1.html"; //original index
    const char *output_directory = "data";
    char *html;
    size_t html_length;
    size_t i;
    int failed = 0;

    if (argc > 3) {
        fprintf(stderr, "Usage: %s [index1.html [output-directory]]\n", argv[0]);
        return EXIT_FAILURE;
    }
    if (argc >= 2)
        input_path = argv[1];
    if (argc >= 3)
        output_directory = argv[2];

    html = read_entire_file(input_path, &html_length);
    if (!html)
        return EXIT_FAILURE;
    if (ensure_output_directory(output_directory) != 0) {
        free(html);
        return EXIT_FAILURE;
    }

    printf("SQLite %s\n", sqlite3_libversion());
    for (i = 0; i < sizeof(READING_SOURCES) / sizeof(READING_SOURCES[0]); ++i) {
        char *json;
        size_t json_length;

        json = extract_json_object(html, html_length,
                                   READING_SOURCES[i].constant_name, &json_length);
        if (!json) {
            failed = 1;
            continue;
        }
        if (write_readings_database(output_directory, &READING_SOURCES[i],
                                    json, json_length) != 0)
            failed = 1;
        free(json);
    }

    {
        char *json;
        size_t json_length;

        json = extract_json_object(html, html_length, "S2T", &json_length);
        if (!json) {
            failed = 1;
        } else {
            if (write_s2t_database(output_directory, json, json_length) != 0)
                failed = 1;
            free(json);
        }
    }

    free(html);
    if (failed) {
        fprintf(stderr, "get_data: one or more databases could not be generated\n");
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}