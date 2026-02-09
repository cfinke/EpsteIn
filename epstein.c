/*
 * Search Epstein files for mentions of LinkedIn connections.
 *
 * Usage:
 *     ./epstein --connections <linkedin_csv> [--output <report.html>]
 *
 * Build:
 *     make
 *
 * Dependencies:
 *     libcurl (apt install libcurl4-openssl-dev / brew install curl)
 *     cJSON   (vendored: cJSON.c + cJSON.h)
 */

#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <getopt.h>
#include <curl/curl.h>
#include "cJSON.h"

#define API_BASE_URL "https://analytics.dugganusa.com/api/v1/search"
#define PDF_BASE_URL "https://www.justice.gov/epstein/files/"
#define MAX_FIELD    512
#define MAX_HITS     100
#define INITIAL_BUF  4096

static volatile sig_atomic_t interrupted = 0;

static void sigint_handler(int sig) {
    (void)sig;
    interrupted = 1;
}

/* ---- Growable buffer for curl responses ---- */

typedef struct {
    char  *data;
    size_t len;
    size_t cap;
} Buffer;

static void buf_init(Buffer *b) {
    b->cap  = INITIAL_BUF;
    b->data = malloc(b->cap);
    b->data[0] = '\0';
    b->len  = 0;
}

static void buf_free(Buffer *b) {
    free(b->data);
    b->data = NULL;
    b->len = b->cap = 0;
}

static size_t curl_write_cb(void *ptr, size_t size, size_t nmemb, void *userdata) {
    size_t total = size * nmemb;
    Buffer *b = userdata;
    while (b->len + total + 1 > b->cap) {
        b->cap *= 2;
        b->data = realloc(b->data, b->cap);
    }
    memcpy(b->data + b->len, ptr, total);
    b->len += total;
    b->data[b->len] = '\0';
    return total;
}

/* ---- Data structures ---- */

typedef struct {
    char first_name[MAX_FIELD];
    char last_name[MAX_FIELD];
    char full_name[MAX_FIELD];
    char company[MAX_FIELD];
    char position[MAX_FIELD];
} Contact;

typedef struct {
    char content_preview[2048];
    char file_path[MAX_FIELD];
} Hit;

typedef struct {
    char name[MAX_FIELD];
    char first_name[MAX_FIELD];
    char last_name[MAX_FIELD];
    char company[MAX_FIELD];
    char position[MAX_FIELD];
    int  total_mentions;
    Hit *hits;
    int  num_hits;
} Result;

/* ---- URL encoding ---- */

static char *url_encode(const char *str) {
    size_t len = strlen(str);
    char *out = malloc(len * 3 + 1);
    char *p = out;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = str[i];
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~') {
            *p++ = c;
        } else {
            sprintf(p, "%%%02X", c);
            p += 3;
        }
    }
    *p = '\0';
    return out;
}

static char *url_encode_path(const char *str) {
    size_t len = strlen(str);
    char *out = malloc(len * 3 + 1);
    char *p = out;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = str[i];
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~' || c == '/') {
            *p++ = c;
        } else {
            sprintf(p, "%%%02X", c);
            p += 3;
        }
    }
    *p = '\0';
    return out;
}

/* ---- HTML escaping ---- */

static void html_escape_to(FILE *f, const char *str) {
    for (; *str; str++) {
        switch (*str) {
            case '&':  fputs("&amp;",  f); break;
            case '<':  fputs("&lt;",   f); break;
            case '>':  fputs("&gt;",   f); break;
            case '"':  fputs("&quot;", f); break;
            case '\'': fputs("&#39;",  f); break;
            default:   fputc(*str, f);     break;
        }
    }
}

/* ---- Base64 encoding ---- */

static const char b64_table[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static char *base64_encode(const unsigned char *data, size_t len) {
    size_t out_len = 4 * ((len + 2) / 3);
    char *out = malloc(out_len + 1);
    char *p = out;

    for (size_t i = 0; i < len; i += 3) {
        unsigned int n = (unsigned int)data[i] << 16;
        if (i + 1 < len) n |= (unsigned int)data[i + 1] << 8;
        if (i + 2 < len) n |= (unsigned int)data[i + 2];

        *p++ = b64_table[(n >> 18) & 0x3F];
        *p++ = b64_table[(n >> 12) & 0x3F];
        *p++ = (i + 1 < len) ? b64_table[(n >> 6) & 0x3F] : '=';
        *p++ = (i + 2 < len) ? b64_table[n & 0x3F] : '=';
    }
    *p = '\0';
    return out;
}

/* ---- CSV parsing ---- */

/*
 * Parse one CSV field (handles double-quoted fields).
 * Writes field value into `out`. Returns pointer to start of next field,
 * or NULL if we've reached end of line.
 */
static const char *parse_csv_field(const char *p, char *out, size_t max_len) {
    size_t i = 0;

    if (*p == '"') {
        p++;
        while (*p && i < max_len - 1) {
            if (*p == '"') {
                if (*(p + 1) == '"') {
                    out[i++] = '"';
                    p += 2;
                } else {
                    p++;
                    break;
                }
            } else {
                out[i++] = *p++;
            }
        }
    } else {
        while (*p && *p != ',' && *p != '\n' && *p != '\r' && i < max_len - 1)
            out[i++] = *p++;
    }
    out[i] = '\0';

    if (*p == ',')
        return p + 1;
    return NULL;
}

static int find_column(const char *header, const char *name) {
    int col = 0;
    const char *p = header;
    char field[MAX_FIELD];

    while (p) {
        memset(field, 0, sizeof(field));
        p = parse_csv_field(p, field, sizeof(field));
        if (strcmp(field, name) == 0)
            return col;
        col++;
        if (!p) break;
    }
    return -1;
}

static int parse_linkedin_contacts(const char *path, Contact **out_contacts) {
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "Error: Cannot open file: %s\n", path);
        return 0;
    }

    char line[8192];
    char *header_line = NULL;

    /* Skip lines until we find the header row */
    while (fgets(line, sizeof(line), f)) {
        if (strstr(line, "First Name") && strstr(line, "Last Name")) {
            header_line = strdup(line);
            break;
        }
    }

    if (!header_line) {
        fclose(f);
        return 0;
    }

    int col_first    = find_column(header_line, "First Name");
    int col_last     = find_column(header_line, "Last Name");
    int col_company  = find_column(header_line, "Company");
    int col_position = find_column(header_line, "Position");
    free(header_line);

    if (col_first < 0 || col_last < 0) {
        fclose(f);
        return 0;
    }

    int cap = 256, count = 0;
    Contact *contacts = malloc(cap * sizeof(Contact));

    while (fgets(line, sizeof(line), f)) {
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = '\0';
        if (len == 0) continue;

        char fields[20][MAX_FIELD];
        memset(fields, 0, sizeof(fields));

        const char *p = line;
        int ncols = 0;
        while (p && ncols < 20) {
            p = parse_csv_field(p, fields[ncols], MAX_FIELD);
            ncols++;
            if (!p) break;
        }

        char *first = (col_first < ncols)    ? fields[col_first]    : fields[0];
        char *last  = (col_last  < ncols)    ? fields[col_last]     : fields[0];

        /* Trim leading whitespace */
        while (*first == ' ') first++;
        while (*last  == ' ') last++;

        /* Remove credentials after comma in last name */
        char *comma = strchr(last, ',');
        if (comma) *comma = '\0';

        /* Trim trailing whitespace */
        size_t last_len = strlen(last);
        while (last_len > 0 && last[last_len - 1] == ' ')
            last[--last_len] = '\0';

        if (strlen(first) == 0 || strlen(last) == 0)
            continue;

        if (count >= cap) {
            cap *= 2;
            contacts = realloc(contacts, cap * sizeof(Contact));
        }

        Contact *c = &contacts[count++];
        memset(c, 0, sizeof(*c));
        strncpy(c->first_name, first, MAX_FIELD - 1);
        strncpy(c->last_name,  last,  MAX_FIELD - 1);
        snprintf(c->full_name, MAX_FIELD, "%s %s", first, last);

        if (col_company >= 0 && col_company < ncols)
            strncpy(c->company, fields[col_company], MAX_FIELD - 1);
        if (col_position >= 0 && col_position < ncols)
            strncpy(c->position, fields[col_position], MAX_FIELD - 1);
    }

    fclose(f);
    *out_contacts = contacts;
    return count;
}

/* ---- Retry-After header parsing ---- */

static int retry_after_value = 0;

static size_t header_cb(char *buffer, size_t size, size_t nitems, void *userdata) {
    (void)userdata;
    size_t total = size * nitems;
    if (total > 12 && strncasecmp(buffer, "Retry-After:", 12) == 0)
        retry_after_value = atoi(buffer + 12);
    return total;
}

/* ---- API search ---- */

static double search_epstein_files(const char *name, double delay, Result *result) {
    char quoted[MAX_FIELD + 4];
    snprintf(quoted, sizeof(quoted), "\"%s\"", name);

    char *encoded = url_encode(quoted);
    char url[2048];
    snprintf(url, sizeof(url), "%s?q=%s&indexes=epstein_files", API_BASE_URL, encoded);
    free(encoded);

    result->total_mentions = 0;
    result->hits = NULL;
    result->num_hits = 0;

    CURL *curl = curl_easy_init();
    if (!curl) return delay;

    Buffer buf;
    buf_init(&buf);

    while (1) {
        buf.len = 0;
        buf.data[0] = '\0';
        retry_after_value = 0;

        curl_easy_setopt(curl, CURLOPT_URL, url);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);
        curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION, header_cb);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);
        curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);

        CURLcode res = curl_easy_perform(curl);
        if (res != CURLE_OK) {
            fprintf(stderr, "Warning: API request failed for '%s': %s\n",
                    name, curl_easy_strerror(res));
            break;
        }

        long http_code;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);

        if (http_code == 429) {
            if (retry_after_value > 0)
                delay = retry_after_value;
            else
                delay *= 2;
            printf(" [429 rate limited, retrying in %.0fs]", delay);
            fflush(stdout);
            usleep((unsigned)(delay * 1000000));
            continue;
        }

        if (http_code != 200) {
            fprintf(stderr, "Warning: HTTP %ld for '%s'\n", http_code, name);
            break;
        }

        /* Parse JSON response */
        cJSON *json = cJSON_Parse(buf.data);
        if (!json) break;

        cJSON *success = cJSON_GetObjectItem(json, "success");
        if (cJSON_IsTrue(success)) {
            cJSON *data = cJSON_GetObjectItem(json, "data");
            if (data) {
                cJSON *total_hits = cJSON_GetObjectItem(data, "totalHits");
                if (cJSON_IsNumber(total_hits))
                    result->total_mentions = (int)total_hits->valuedouble;

                cJSON *hits_arr = cJSON_GetObjectItem(data, "hits");
                if (cJSON_IsArray(hits_arr)) {
                    int n = cJSON_GetArraySize(hits_arr);
                    if (n > MAX_HITS) n = MAX_HITS;
                    result->hits = calloc(n, sizeof(Hit));
                    result->num_hits = n;

                    for (int i = 0; i < n; i++) {
                        cJSON *hit = cJSON_GetArrayItem(hits_arr, i);
                        cJSON *preview = cJSON_GetObjectItem(hit, "content_preview");
                        if (!preview || !cJSON_IsString(preview))
                            preview = cJSON_GetObjectItem(hit, "content");
                        if (preview && cJSON_IsString(preview))
                            strncpy(result->hits[i].content_preview,
                                    preview->valuestring,
                                    sizeof(result->hits[i].content_preview) - 1);

                        cJSON *fp = cJSON_GetObjectItem(hit, "file_path");
                        if (fp && cJSON_IsString(fp))
                            strncpy(result->hits[i].file_path,
                                    fp->valuestring,
                                    sizeof(result->hits[i].file_path) - 1);
                    }
                }
            }
        }
        cJSON_Delete(json);
        break;
    }

    buf_free(&buf);
    curl_easy_cleanup(curl);
    return delay;
}

/* ---- HTML report generation ---- */

static void generate_html_report(Result *results, int num_results,
                                  const char *output_path, const char *exe_dir) {
    int contacts_with_mentions = 0;
    for (int i = 0; i < num_results; i++)
        if (results[i].total_mentions > 0)
            contacts_with_mentions++;

    FILE *f = fopen(output_path, "w");
    if (!f) {
        fprintf(stderr, "Error: Cannot open output file: %s\n", output_path);
        return;
    }

    /* Load and base64-encode logo, or fall back to text header */
    char logo_path[1024];
    snprintf(logo_path, sizeof(logo_path), "%s/assets/logo.png", exe_dir);

    char *logo_html = NULL;
    FILE *logo_f = fopen(logo_path, "rb");
    if (logo_f) {
        fseek(logo_f, 0, SEEK_END);
        long logo_size = ftell(logo_f);
        fseek(logo_f, 0, SEEK_SET);
        unsigned char *logo_data = malloc(logo_size);
        if (fread(logo_data, 1, logo_size, logo_f) == (size_t)logo_size) {
            char *b64 = base64_encode(logo_data, logo_size);
            size_t html_len = strlen(b64) + 200;
            logo_html = malloc(html_len);
            snprintf(logo_html, html_len,
                "<img src=\"data:image/png;base64,%s\" alt=\"EpsteIn\" class=\"logo\">", b64);
            free(b64);
        }
        free(logo_data);
        fclose(logo_f);
    }
    if (!logo_html)
        logo_html = strdup("<h1 class=\"logo\" style=\"text-align: center;\">EpsteIn</h1>");

    /* Write HTML head + summary */
    fprintf(f,
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "    <meta charset=\"UTF-8\">\n"
        "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        "    <title>EpsteIn: Which LinkedIn Connections Appear in the Epstein Files?</title>\n"
        "    <style>\n"
        "        * { box-sizing: border-box; }\n"
        "        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;"
        " line-height: 1.6; max-width: 1200px; margin: 0 auto; padding: 20px; background-color: #f5f5f5; }\n"
        "        .logo { display: block; max-width: 300px; margin: 0 auto 20px auto; }\n"
        "        .summary { background: #fff; padding: 20px; border-radius: 8px;"
        " margin-bottom: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }\n"
        "        .contact { background: #fff; padding: 20px; margin-bottom: 20px;"
        " border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }\n"
        "        .contact-header { display: flex; justify-content: space-between;"
        " align-items: center; border-bottom: 1px solid #eee;"
        " padding-bottom: 10px; margin-bottom: 15px; }\n"
        "        .contact-name { font-size: 1.4em; font-weight: bold; color: #333; }\n"
        "        .contact-info { color: #666; font-size: 0.9em; }\n"
        "        .hit-count { background: #e74c3c; color: white; padding: 5px 15px;"
        " border-radius: 20px; font-weight: bold; }\n"
        "        .hit { background: #f9f9f9; padding: 15px; margin-bottom: 10px;"
        " border-radius: 4px; border-left: 3px solid #3498db; }\n"
        "        .hit-preview { color: #444; margin-bottom: 10px; font-size: 0.95em; }\n"
        "        .hit-link { display: inline-block; color: #3498db;"
        " text-decoration: none; font-size: 0.85em; }\n"
        "        .hit-link:hover { text-decoration: underline; }\n"
        "        .no-results { color: #999; font-style: italic; }\n"
        "        .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd;"
        " text-align: center; color: #666; font-size: 0.9em; }\n"
        "        .footer a { color: #3498db; text-decoration: none; }\n"
        "        .footer a:hover { text-decoration: underline; }\n"
        "    </style>\n"
        "</head>\n<body>\n"
        "    %s\n"
        "    <div class=\"summary\">\n"
        "        <strong>Total connections searched:</strong> %d<br>\n"
        "        <strong>Connections with mentions:</strong> %d\n"
        "    </div>\n",
        logo_html, num_results, contacts_with_mentions);

    free(logo_html);

    /* Write each contact with mentions */
    for (int i = 0; i < num_results; i++) {
        Result *r = &results[i];
        if (r->total_mentions == 0) continue;

        fprintf(f,
            "    <div class=\"contact\">\n"
            "        <div class=\"contact-header\">\n"
            "            <div>\n"
            "                <div class=\"contact-name\">");
        html_escape_to(f, r->name);
        fprintf(f, "</div>\n                <div class=\"contact-info\">");

        if (r->position[0] && r->company[0]) {
            html_escape_to(f, r->position);
            fputs(" at ", f);
            html_escape_to(f, r->company);
        } else if (r->position[0]) {
            html_escape_to(f, r->position);
        } else if (r->company[0]) {
            html_escape_to(f, r->company);
        }

        fprintf(f,
            "</div>\n"
            "            </div>\n"
            "            <div class=\"hit-count\">%d mentions</div>\n"
            "        </div>\n", r->total_mentions);

        if (r->num_hits > 0) {
            for (int j = 0; j < r->num_hits; j++) {
                Hit *h = &r->hits[j];

                fprintf(f,
                    "        <div class=\"hit\">\n"
                    "            <div class=\"hit-preview\">");

                /* Truncate preview to 500 chars */
                char preview[501];
                strncpy(preview, h->content_preview, 500);
                preview[500] = '\0';
                html_escape_to(f, preview);
                fprintf(f, "</div>\n");

                if (h->file_path[0]) {
                    /* Replace "dataset" with "DataSet" in path */
                    char fixed_path[MAX_FIELD];
                    strncpy(fixed_path, h->file_path, MAX_FIELD - 1);
                    fixed_path[MAX_FIELD - 1] = '\0';
                    char *pos = strstr(fixed_path, "dataset");
                    if (pos)
                        memcpy(pos, "DataSet", 7);

                    char *enc_path = url_encode_path(fixed_path);
                    char pdf_url[2048];

                    if (fixed_path[0] == '/') {
                        /* Strip trailing slash from base to avoid double slash */
                        char base[256];
                        strncpy(base, PDF_BASE_URL, sizeof(base) - 1);
                        base[sizeof(base) - 1] = '\0';
                        size_t blen = strlen(base);
                        if (blen > 0 && base[blen - 1] == '/')
                            base[blen - 1] = '\0';
                        snprintf(pdf_url, sizeof(pdf_url), "%s%s", base, enc_path);
                    } else {
                        snprintf(pdf_url, sizeof(pdf_url), "%s%s", PDF_BASE_URL, enc_path);
                    }
                    free(enc_path);

                    fputs("            <a class=\"hit-link\" href=\"", f);
                    html_escape_to(f, pdf_url);
                    fputs("\" target=\"_blank\">View PDF: ", f);
                    html_escape_to(f, fixed_path);
                    fputs("</a>\n", f);
                }
                fputs("        </div>\n", f);
            }
        } else {
            fputs("        <div class=\"no-results\">Hit details not available</div>\n", f);
        }

        fputs("    </div>\n", f);
    }

    fprintf(f,
        "    <div class=\"footer\">\n"
        "        Epstein files indexed by"
        " <a href=\"https://dugganusa.com\" target=\"_blank\">DugganUSA.com</a>\n"
        "    </div>\n"
        "</body>\n</html>\n");

    fclose(f);
}

/* ---- qsort comparator (descending by mentions) ---- */

static int cmp_results(const void *a, const void *b) {
    return ((const Result *)b)->total_mentions - ((const Result *)a)->total_mentions;
}

/* ---- Usage text ---- */

static void print_usage(void) {
    fputs(
        "\nNo connections file specified.\n\n"
        "To export your LinkedIn connections:\n"
        "  1. Go to linkedin.com and log in\n"
        "  2. Click your profile icon in the top right\n"
        "  3. Select \"Settings & Privacy\"\n"
        "  4. Click \"Data privacy\" in the left sidebar\n"
        "  5. Under \"How LinkedIn uses your data\", click \"Get a copy of your data\"\n"
        "  6. Select \"Connections\" (or \"Want something in particular?\" and check Connections)\n"
        "  7. Click \"Request archive\"\n"
        "  8. Wait for LinkedIn's email (may take up to 24 hours)\n"
        "  9. Download and extract the ZIP file\n"
        "  10. Use the Connections.csv file with this program:\n\n"
        "     ./epstein --connections /path/to/Connections.csv\n\n",
        stderr);
}

/* ---- Main ---- */

int main(int argc, char *argv[]) {
    const char *connections_path = NULL;
    const char *output_path = "EpsteIn.html";

    static struct option long_opts[] = {
        {"connections", required_argument, NULL, 'c'},
        {"output",      required_argument, NULL, 'o'},
        {"help",        no_argument,       NULL, 'h'},
        {NULL, 0, NULL, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "c:o:h", long_opts, NULL)) != -1) {
        switch (opt) {
            case 'c': connections_path = optarg; break;
            case 'o': output_path = optarg; break;
            case 'h':
            default:
                fprintf(stderr, "Usage: %s --connections <csv> [--output <report.html>]\n",
                        argv[0]);
                return (opt == 'h') ? 0 : 1;
        }
    }

    if (!connections_path) {
        print_usage();
        return 1;
    }

    FILE *test = fopen(connections_path, "r");
    if (!test) {
        fprintf(stderr, "Error: Connections file not found: %s\n", connections_path);
        return 1;
    }
    fclose(test);

    /* Determine executable directory (for finding assets/) */
    char exe_dir[1024] = ".";
    char *slash = strrchr(argv[0], '/');
    if (slash) {
        size_t dirlen = (size_t)(slash - argv[0]);
        if (dirlen < sizeof(exe_dir)) {
            memcpy(exe_dir, argv[0], dirlen);
            exe_dir[dirlen] = '\0';
        }
    }

    /* Parse contacts */
    printf("Reading LinkedIn connections from: %s\n", connections_path);
    Contact *contacts = NULL;
    int num_contacts = parse_linkedin_contacts(connections_path, &contacts);
    printf("Found %d connections\n", num_contacts);

    if (num_contacts == 0) {
        fprintf(stderr, "No connections found in CSV. Check the file format.\n");
        free(contacts);
        return 1;
    }

    /* Install Ctrl+C handler */
    struct sigaction sa;
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);

    curl_global_init(CURL_GLOBAL_DEFAULT);

    /* Search each contact */
    printf("Searching Epstein files API...\n");
    printf("(Press Ctrl+C to stop and generate a partial report)\n\n");

    Result *results = calloc(num_contacts, sizeof(Result));
    int num_results = 0;
    double delay = 0.25;

    for (int i = 0; i < num_contacts && !interrupted; i++) {
        Contact *c = &contacts[i];
        printf("  [%d/%d] %s", i + 1, num_contacts, c->full_name);
        fflush(stdout);

        Result *r = &results[num_results];
        strncpy(r->name,       c->full_name,  MAX_FIELD - 1);
        strncpy(r->first_name, c->first_name, MAX_FIELD - 1);
        strncpy(r->last_name,  c->last_name,  MAX_FIELD - 1);
        strncpy(r->company,    c->company,    MAX_FIELD - 1);
        strncpy(r->position,   c->position,   MAX_FIELD - 1);

        delay = search_epstein_files(c->full_name, delay, r);
        printf(" -> %d hits\n", r->total_mentions);
        num_results++;

        if (i < num_contacts - 1 && !interrupted)
            usleep((unsigned)(delay * 1000000));
    }

    if (interrupted) {
        printf("\n\nSearch interrupted by user (Ctrl+C).\n");
        if (num_results == 0) {
            printf("No results collected yet. Exiting without generating report.\n");
            free(contacts);
            free(results);
            curl_global_cleanup();
            return 0;
        }
        printf("Generating partial report with %d of %d contacts searched...\n",
               num_results, num_contacts);
    }

    /* Sort by mentions descending */
    qsort(results, num_results, sizeof(Result), cmp_results);

    /* Generate HTML report */
    printf("\nWriting report to: %s\n", output_path);
    generate_html_report(results, num_results, output_path, exe_dir);

    /* Print summary */
    int with_mentions = 0;
    for (int i = 0; i < num_results; i++)
        if (results[i].total_mentions > 0)
            with_mentions++;

    printf("\n============================================================\n");
    printf("SUMMARY\n");
    printf("============================================================\n");
    printf("Total connections searched: %d\n", num_results);
    printf("Connections with mentions: %d\n", with_mentions);

    if (with_mentions > 0) {
        printf("\nTop mentions:\n");
        int shown = 0;
        for (int i = 0; i < num_results && shown < 20; i++) {
            if (results[i].total_mentions > 0) {
                printf("  %6d - %s\n", results[i].total_mentions, results[i].name);
                shown++;
            }
        }
    } else {
        printf("\nNo connections found in the Epstein files.\n");
    }

    printf("\nFull report saved to: %s\n", output_path);

    /* Cleanup */
    for (int i = 0; i < num_results; i++)
        free(results[i].hits);
    free(results);
    free(contacts);
    curl_global_cleanup();

    return 0;
}
