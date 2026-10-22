/* Public C symbol visibility. License: Apache-2.0. */
#ifndef QVF_EXPORT_H
#define QVF_EXPORT_H
#if defined(_WIN32) && defined(QVF_SHARED)
# if defined(QVF_BUILDING_LIBRARY)
#  define QVF_API __declspec(dllexport)
# else
#  define QVF_API __declspec(dllimport)
# endif
#elif defined(__GNUC__) && defined(QVF_SHARED)
# define QVF_API __attribute__((visibility("default")))
#else
# define QVF_API
#endif
#endif
