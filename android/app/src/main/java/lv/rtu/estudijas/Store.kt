package lv.rtu.estudijas

import android.content.Context
import java.io.File

/** Tā pati glabātuve, ko lieto saskarne (Native.load/save). */
object Store {
    private fun dir(ctx: Context) = File(ctx.filesDir, "store").apply { mkdirs() }
    fun file(ctx: Context, key: String) = File(dir(ctx), key.replace(Regex("[^A-Za-z0-9_-]"), "_") + ".json")
    fun load(ctx: Context, key: String): String? = file(ctx, key).takeIf { it.exists() }?.readText()
    fun save(ctx: Context, key: String, value: String) {
        val f = file(ctx, key)
        if (value.isEmpty()) { f.delete(); return }
        val tmp = File(f.path + ".tmp")
        tmp.writeText(value)
        tmp.renameTo(f)
    }
}
