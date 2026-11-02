package lv.rtu.estudijas

import android.os.Build
import android.view.View
import android.view.WindowInsets

/** Android 15+ zīmē lietotni zem sistēmas joslām — atstāj vietu statusa/navigācijas joslām un tastatūrai. */
fun View.padForSystemBars() {
    if (Build.VERSION.SDK_INT < 35) return
    setOnApplyWindowInsetsListener { v, insets ->
        val i = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or WindowInsets.Type.ime())
        v.setPadding(i.left, i.top, i.right, i.bottom)
        WindowInsets.CONSUMED
    }
}
